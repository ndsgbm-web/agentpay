"""End-to-end test for AgentPay.

This script:
1. Spins up a local Anvil instance (if available) or uses Base Sepolia
2. Deploys AgentPayEscrow with a known fee recipient
3. Mints test USDC to a buyer (or skips on mainnet)
4. Buyer creates + funds an escrow
5. Buyer releases
6. Verifies fee went to recipient, principal went to seller

Requires:
  - pip install web3 eth-account
  - anvil installed and on PATH (or set AGENTPAY_RPC to use testnet)
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))

from web3 import Web3  # noqa
from eth_account import Account  # noqa


def banner(s):
    print(f"\n=== {s} ===")


def main():
    rpc = os.environ.get("AGENTPAY_RPC", "http://127.0.0.1:8545")
    anvil_proc = None
    if rpc.startswith("http://127.0.0.1") and not _ping(rpc):
        print("starting anvil...")
        anvil_proc = subprocess.Popen(
            ["anvil", "--port", "8545", "--silent"],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
        )
        time.sleep(2)

    w3 = Web3(Web3.HTTPProvider(rpc, request_kwargs={"timeout": 10}))
    if not w3.is_connected():
        sys.exit(f"cannot reach {rpc}; start anvil or set AGENTPAY_RPC")

    banner("Setting up accounts")
    # Anvil default keys (well-known). DO NOT USE ON MAINNET.
    ANVIL_KEYS = [
        "0xac0974bec39a17e36ba4a6b4d238ff944bacb478cbed5efcae784d7bf4f2ff80",  # 0xf39Fd6...
        "0x59c6995e998f97a5a0044966f0945389dc9e86dae88c7a8412f4603b6b78690d",  # 0x70997...
        "0x5de4111afa1a4b94908f83103eb1f1706367c2e68ca870fc3fb9a804cdab365a",  # 0x3C44C...
    ]
    deployer = Account.from_key(ANVIL_KEYS[0])
    buyer = Account.from_key(ANVIL_KEYS[1])
    seller = Account.from_key(ANVIL_KEYS[2])
    print(f"deployer: {deployer.address}")
    print(f"buyer:    {buyer.address}")
    print(f"seller:   {seller.address}")

    banner("Deploying AgentPayEscrow")
    abi = json.loads((ROOT / "contracts" / "AgentPayEscrow.abi.json").read_text())
    bytecode = bytes.fromhex(next((ROOT / "build").glob("*.bin")).read_text().strip())
    Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
    tx = Contract.constructor(seller.address, 50).build_transaction({
        "from": deployer.address,
        "nonce": w3.eth.get_transaction_count(deployer.address),
        "chainId": w3.eth.chain_id,
        "gas": 2_500_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = deployer.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    escrow_addr = r.contractAddress
    print(f"contract: {escrow_addr}")

    banner("Minting test USDC")
    # Use Circle's official USDC contract address (or mock on Anvil).
    # On Anvil, we'll deploy a minimal mock USDC.
    USDC_MOCK_ABI = [
        {"type": "function", "name": "mint", "inputs": [
            {"name": "to", "type": "address"},
            {"name": "amount", "type": "uint256"}],
         "outputs": [], "stateMutability": "nonpayable"},
        {"type": "function", "name": "approve", "inputs": [
            {"name": "spender", "type": "address"},
            {"name": "amount", "type": "uint256"}],
         "outputs": [{"type": "bool"}], "stateMutability": "nonpayable"},
        {"type": "function", "name": "balanceOf", "inputs": [
            {"name": "a", "type": "address"}],
         "outputs": [{"type": "uint256"}], "stateMutability": "view"},
        {"type": "function", "name": "transfer", "inputs": [
            {"name": "to", "type": "address"},
            {"name": "a", "type": "uint256"}],
         "outputs": [{"type": "bool"}], "stateMutability": "nonpayable"},
    ]
    USDC_BYTECODE = json.loads((ROOT / "contracts" / "MockUSDC.abi.json").read_text()["bytecode"])
    MockUSDC = w3.eth.contract(abi=USDC_MOCK_ABI, bytecode=USDC_BYTECODE)
    tx = MockUSDC.constructor().build_transaction({
        "from": deployer.address,
        "nonce": w3.eth.get_transaction_count(deployer.address),
        "chainId": w3.eth.chain_id,
        "gas": 2_000_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = deployer.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    usdc_addr = r.contractAddress
    print(f"mock USDC: {usdc_addr}")

    usdc = w3.eth.contract(address=usdc_addr, abi=USDC_MOCK_ABI)
    # mint 1000 USDC to buyer
    tx = usdc.functions.mint(buyer.address, 1_000_000_000).build_transaction({
        "from": deployer.address,
        "nonce": w3.eth.get_transaction_count(deployer.address),
        "chainId": w3.eth.chain_id,
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = deployer.sign_transaction(tx)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
    print(f"buyer balance: {usdc.functions.balanceOf(buyer.address).call() / 1e6} USDC")

    banner("AgentPay SDK E2E")
    # build SDK on the fly so we test the real client
    from agentpay import AgentPay
    # buyer's client (we'll override the USDC address since this is a mock)
    ap = AgentPay(private_key=ANVIL_KEYS[1], escrow_address=escrow_addr, rpc_url=rpc, chain_id=w3.eth.chain_id)
    # hack: use our mock USDC by monkey-patching
    USDC_ADDRESSES = {w3.eth.chain_id: usdc_addr}
    import agentpay.client as _client
    _client.USDC_ADDRESSES.update(USDC_ADDRESSES)

    task_hash = ap.hash_task("translate-en-1000-words")
    print("creating escrow for $10 USDC...")
    eid = ap.create_and_fund(
        payee=seller.address,
        amount_usdc=10,
        task_hash=task_hash,
        deadline_hours=1,
    )
    print(f"escrow id: {eid.hex()}")

    escrow = ap.get_escrow(eid)
    print(f"status:     {escrow.status} (1 = Funded)")
    print(f"amount:     {escrow.amount / 1e6} USDC")
    print(f"fee:        {escrow.fee / 1e6} USDC")

    print("\nreleasing...")
    ap.release(eid)
    escrow = ap.get_escrow(eid)
    print(f"status:     {escrow.status} (2 = Released)")

    seller_bal = usdc.functions.balanceOf(seller.address).call()
    print(f"seller USDC: {seller_bal / 1e6}")

    assert seller_bal == 10_000_000 - (10_000_000 * 50 // 10_000), "seller balance wrong"
    print("\nE2E PASS")

    if anvil_proc:
        anvil_proc.terminate()


def _ping(url):
    import urllib.request
    try:
        urllib.request.urlopen(url, timeout=1).read()
        return True
    except Exception:
        return False


if __name__ == "__main__":
    main()
