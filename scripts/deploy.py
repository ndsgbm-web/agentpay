"""Deploy AgentPay (Escrow + Vault + Mock Aave for testnets).

Usage:
    # Testnet with mock Aave (Base Sepolia, no real yield):
    python deploy.py --private-key $PK --network base-sepolia --mode mock \\
        --fee-recipient 0x... --yield-recipient 0x...

    # Mainnet (production): pass real Aave Pool + USDC
    python deploy.py --private-key $PK --network base --mode prod \\
        --fee-recipient 0x... --yield-recipient 0x... \\
        --usdc 0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913 \\
        --aave-pool 0xA238Dd80C259a72e81d7e4664a9801593F98d1c5
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD = ROOT / "build"
CONTRACTS = ROOT / "contracts"
MOCKS = CONTRACTS / "mocks"

NETWORKS = {
    "base": {
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "explorer": "https://basescan.org",
        "verify_url": "https://api.basescan.org/api",
        "usdc": "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",
        "aave_pool": "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5",
    },
    "base-sepolia": {
        "chain_id": 84532,
        "rpc": "https://sepolia.base.org",
        "explorer": "https://sepolia.basescan.org",
        "verify_url": "https://api-sepolia.basescan.org/api",
        "usdc": "0x036CbD53842c5426634e7929541eC2318f3dCF7e",
        "aave_pool": None,
    },
}


def load_contract(abi_path: Path, bin_path: Path):
    data = json.loads(abi_path.read_text())
    abi = data["abi"] if isinstance(data, dict) and "abi" in data else data
    bytecode = bin_path.read_text().strip()
    return abi, bytes.fromhex(bytecode)


def deploy(w3, acct, abi, bytecode, *args, gas=3_000_000):
    C = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = C.constructor(*args).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
        "gas": gas,
        "gasPrice": w3.eth.gas_price,
    })
    try:
        tx["gas"] = w3.eth.estimate_gas({k: v for k, v in tx.items() if k != "gas"})
    except Exception:
        pass
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=300)
    assert r.status == 1, f"deploy failed: {r}"
    return r.contractAddress


def send(w3, acct, fn, gas=200_000, value=0):
    tx = fn.build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id,
        "gas": gas,
        "gasPrice": w3.eth.gas_price,
        "value": value,
    })
    try:
        tx["gas"] = w3.eth.estimate_gas({k: v for k, v in tx.items() if k != "gas"})
    except Exception:
        pass
    signed = acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=300)
    assert r.status == 1, f"tx {fn.fn_name} failed: {r}"
    return r


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--private-key", required=True)
    p.add_argument("--network", default="base-sepolia", choices=list(NETWORKS.keys()))
    p.add_argument("--mode", default="mock", choices=["mock", "prod"])
    p.add_argument("--fee-recipient", required=True)
    p.add_argument("--yield-recipient", required=True)
    p.add_argument("--fee-bps", type=int, default=50)
    p.add_argument("--usdc")
    p.add_argument("--aave-pool")
    p.add_argument("--verify", action="store_true")
    p.add_argument("--etherscan-key", default=os.environ.get("BASESCAN_API_KEY"))
    args = p.parse_args()

    from web3 import Web3
    from eth_account import Account

    net = NETWORKS[args.network]
    w3 = Web3(Web3.HTTPProvider(net["rpc"], request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        sys.exit(f"cannot reach {args.network} RPC at {net['rpc']}")

    acct = Account.from_key(args.private_key)
    bal = w3.eth.get_balance(acct.address) / 1e18
    print(f"network:    {args.network} (chain {w3.eth.chain_id})")
    print(f"deployer:   {acct.address}")
    print(f"balance:    {bal:.6f} native")
    if bal < 0.001:
        sys.exit("deployer needs at least 0.001 native for gas; faucet first")

    usdc_addr = Web3.to_checksum_address(args.usdc or net["usdc"])

    if args.mode == "mock":
        print("\n[0/4] deploying MockUSDC (open mint for testnet)...")
        mock_usdc_abi_path = CONTRACTS / "MockUSDC.abi.json"
        mock_usdc_bin_path = BUILD / "MockUSDC.bin"
        if not (mock_usdc_abi_path.exists() and mock_usdc_bin_path.exists()):
            sys.exit("MockUSDC build artifacts missing; compile contracts/MockUSDC.sol first")
        mock_usdc_abi, mock_usdc_bin = load_contract(mock_usdc_abi_path, mock_usdc_bin_path)
        usdc_addr = deploy(w3, acct, mock_usdc_abi, mock_usdc_bin)
        print(f"  usdc (mock): {usdc_addr}")

    print("\n[2/4] deploying AgentPayEscrow...")
    escrow_abi, escrow_bin = load_contract(
        CONTRACTS / "AgentPayEscrow.abi.json",
        BUILD / "AgentPayEscrow.bin",
    )
    escrow_addr = deploy(w3, acct, escrow_abi, escrow_bin,
                         Web3.to_checksum_address(args.fee_recipient), args.fee_bps)
    print(f"  escrow:   {escrow_addr}")
    print(f"  explorer: {net['explorer']}/address/{escrow_addr}")

    if args.mode == "mock":
        print("\n[3/4] deploying MockAave...")
        mock_abi_path = next(MOCKS.glob("MockAave.abi.json"), None)
        mock_bin_path = next(MOCKS.glob("MockAave.bin"), None)
        if not (mock_abi_path and mock_bin_path):
            sys.exit("MockAave build artifacts missing; compile contracts/mocks/MockAave.sol first")
        mock_abi, mock_bin = load_contract(mock_abi_path, mock_bin_path)
        aave_addr = deploy(w3, acct, mock_abi, mock_bin, usdc_addr)
    else:
        aave_addr = args.aave_pool or net["aave_pool"]
        if not aave_addr:
            sys.exit("--aave-pool required for prod mode")
        aave_addr = Web3.to_checksum_address(aave_addr)
    print(f"  aave:     {aave_addr}")

    print("\n[4/4] deploying AgentPayVault...")
    vault_abi, vault_bin = load_contract(
        CONTRACTS / "AgentPayVault.abi.json",
        BUILD / "AgentPayVault.bin",
    )
    vault_addr = deploy(w3, acct, vault_abi, vault_bin, usdc_addr, aave_addr,
                        Web3.to_checksum_address(args.yield_recipient))
    print(f"  vault:    {vault_addr}")

    print("\n[5/4] linking contracts...")
    if args.mode == "mock":
        aave = w3.eth.contract(address=aave_addr, abi=mock_abi)
        send(w3, acct, aave.functions.setVault(vault_addr))
        print(f"  MockAave.vault = {vault_addr}")
    vault = w3.eth.contract(address=vault_addr, abi=vault_abi)
    send(w3, acct, vault.functions.init())
    print(f"  Vault.aUsdc discovered")
    send(w3, acct, vault.functions.setTaskManager(escrow_addr))
    print(f"  Vault.taskManager = {escrow_addr}")

    summary = {
        "network": args.network,
        "chain_id": w3.eth.chain_id,
        "deployer": acct.address,
        "usdc": usdc_addr,
        "aave": aave_addr,
        "aave_mode": args.mode,
        "escrow": escrow_addr,
        "vault": vault_addr,
        "fee_recipient": Web3.to_checksum_address(args.fee_recipient),
        "yield_recipient": Web3.to_checksum_address(args.yield_recipient),
        "fee_bps": args.fee_bps,
    }
    print("\n=== DEPLOY SUMMARY ===")
    print(json.dumps(summary, indent=2))

    if args.verify:
        if not args.etherscan_key:
            print("skip verify (no --etherscan-key)")
        else:
            import requests
            for name, abi, bytecode, addr in [
                ("AgentPayEscrow", escrow_abi, escrow_bin, escrow_addr),
                ("AgentPayVault", vault_abi, vault_bin, vault_addr),
            ]:
                src_path = CONTRACTS / f"{name}.sol"
                if not src_path.exists():
                    print(f"  skip verify {name} (no source)")
                    continue
                print(f"  verifying {name}...")
                r = requests.post(net["verify_url"], data={
                    "apikey": args.etherscan_key,
                    "module": "contract",
                    "action": "verifysourcecode",
                    "contractaddress": addr,
                    "sourceCode": src_path.read_text(),
                    "codeformat": "solidity-single-file",
                    "contractname": name,
                    "compilerversion": "v0.8.24+commit.e11b9ed9",
                    "optimizationUsed": 0,
                }, timeout=60)
                print(f"    {r.json()}")


if __name__ == "__main__":
    main()
