"""Deploy AgentPayEscrow to Base (mainnet or Sepolia).

Usage:
    python deploy.py --private-key $PK --network base-sepolia
    python deploy.py --private-key $PK --network base --verify

Reads compiled bytecode + ABI from build/ (produced by solcjs).
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BUILD_DIR = ROOT / "build"
ABI_PATH = ROOT / "contracts" / "AgentPayEscrow.abi.json"

# Bytecode files from solcjs have a long ugly name; find them.
def find_bytecode() -> bytes:
    candidates = list(BUILD_DIR.glob("*.bin"))
    if not candidates:
        sys.exit(f"no .bin in {BUILD_DIR}; run: solcjs contracts/AgentPayEscrow.sol --bin --abi -o build")
    return bytes.fromhex(candidates[0].read_text().strip())


NETWORKS = {
    "base": {
        "chain_id": 8453,
        "rpc": "https://mainnet.base.org",
        "explorer": "https://basescan.org",
    },
    "base-sepolia": {
        "chain_id": 84532,
        "rpc": "https://sepolia.base.org",
        "explorer": "https://sepolia.basescan.org",
    },
}


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--private-key", required=True, help="deployer private key (hex, 0x...)")
    p.add_argument("--network", default="base-sepolia", choices=list(NETWORKS.keys()))
    p.add_argument("--fee-recipient", required=True, help="address that receives the 0.5% fee")
    p.add_argument("--fee-bps", type=int, default=50, help="fee in basis points (50 = 0.5%)")
    p.add_argument("--verify", action="store_true", help="verify on BaseScan (needs API key)")
    p.add_argument("--etherscan-key", default=os.environ.get("BASESCAN_API_KEY"))
    args = p.parse_args()

    from web3 import Web3
    from eth_account import Account

    net = NETWORKS[args.network]
    w3 = Web3(Web3.HTTPProvider(net["rpc"], request_kwargs={"timeout": 30}))
    if not w3.is_connected():
        sys.exit(f"cannot reach {args.network} RPC")

    acct = Account.from_key(args.private_key)
    print(f"deployer:   {acct.address}")
    print(f"balance:    {w3.eth.get_balance(acct.address) / 1e18:.6f} native")
    print(f"chain id:   {w3.eth.chain_id}")

    abi = json.loads(ABI_PATH.read_text())
    bytecode = find_bytecode()
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)

    tx = Contract.constructor(
        Web3.to_checksum_address(args.fee_recipient),
        args.fee_bps,
    ).build_transaction({
        "from": acct.address,
        "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": net["chain_id"],
        "gas": 2_500_000,
        "gasPrice": w3.eth.gas_price,
    })
    try:
        tx["gas"] = w3.eth.estimate_gas({k: v for k, v in tx.items() if k != "gas"})
    except Exception as e:
        print(f"estimate failed, using 2.5M: {e}")

    signed = acct.sign_transaction(tx)
    print(f"deploying...")
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    print(f"tx: {h.hex()}")
    r = w3.eth.wait_for_transaction_receipt(h, timeout=300)
    addr = r.contractAddress
    print(f"\ndeployed: {addr}")
    print(f"explorer: {net['explorer']}/address/{addr}")

    if args.verify and args.etherscan_key:
        print("\nverifying on BaseScan...")
        verify(addr, abi, bytecode, args)


def verify(address: str, abi, bytecode: bytes, args):
    import requests
    url = {
        "base": "https://api.basescan.org/api",
        "base-sepolia": "https://api-sepolia.basescan.org/api",
    }[args.network]
    r = requests.post(url, data={
        "apikey": args.etherscan_key,
        "module": "contract",
        "action": "verifysourcecode",
        "contractaddress": address,
        "sourceCode": (ROOT / "contracts" / "AgentPayEscrow.sol").read_text(),
        "codeformat": "solidity-single-file",
        "contractname": "AgentPayEscrow",
        "compilerversion": "v0.8.24+commit.e11b9ed9",
        "optimizationUsed": 0,
    })
    print(r.json())


if __name__ == "__main__":
    main()
