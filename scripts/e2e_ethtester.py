"""End-to-end test for AgentPay using eth-tester (no Anvil needed).

Spins up an in-memory EVM, deploys AgentPayEscrow + MockUSDC, then
walks through the full happy path:
  1. Buyer mints test USDC
  2. Buyer creates + funds escrow
  3. Buyer releases
  4. Verify 99.5% to seller, 0.5% to fee recipient

Run: pip install 'agentpay[test]' eth-tester
     python scripts/e2e_ethtester.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))


def banner(s):
    print(f"\n=== {s} ===")


def main():
    try:
        from eth_tester import EthereumTester
        from web3 import Web3
        from web3.providers.eth_tester import EthereumTesterProvider
    except ImportError:
        print("install: pip install eth-tester 'web3>=6.0'")
        sys.exit(1)

    from eth_account import Account

    banner("Spinning up in-memory EVM")
    tester = EthereumTester()
    w3 = Web3(EthereumTesterProvider(tester))
    w3.eth.default_account = w3.eth.accounts[0]
    print(f"chain id: {w3.eth.chain_id}")

    # funded accounts
    keys = tester.backend.account_keys
    deployer_acct = Account.from_key(keys[0])
    buyer_acct    = Account.from_key(keys[1])
    seller_acct   = Account.from_key(keys[2])
    fee_acct      = Account.from_key(keys[3])

    def fund(acct):
        # eth-tester pre-funds accounts; nothing to do
        return w3.eth.get_balance(acct.address)

    banner("Deploying MockUSDC")
    mock_abi = json.loads((ROOT / "contracts" / "MockUSDC.abi.json").read_text())["abi"]
    mock_bin = json.loads((ROOT / "contracts" / "MockUSDC.abi.json").read_text())["bytecode"]
    MockUSDC = w3.eth.contract(abi=mock_abi, bytecode=mock_bin)
    tx = MockUSDC.constructor().build_transaction({
        "from": deployer_acct.address,
        "nonce": w3.eth.get_transaction_count(deployer_acct.address),
        "gas": 2_000_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = deployer_acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    usdc_addr = r.contractAddress
    usdc = w3.eth.contract(address=usdc_addr, abi=mock_abi)
    print(f"MockUSDC: {usdc_addr}")

    banner("Deploying AgentPayEscrow")
    escrow_abi = json.loads((ROOT / "contracts" / "AgentPayEscrow.abi.json").read_text())
    escrow_bin = next((ROOT / "build").glob("*.bin")).read_text().strip()
    Escrow = w3.eth.contract(abi=escrow_abi, bytecode=escrow_bin)
    tx = Escrow.constructor(fee_acct.address, 50).build_transaction({
        "from": deployer_acct.address,
        "nonce": w3.eth.get_transaction_count(deployer_acct.address),
        "gas": 3_000_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = deployer_acct.sign_transaction(tx)
    h = w3.eth.send_raw_transaction(signed.raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h)
    escrow_addr = r.contractAddress
    print(f"Escrow:   {escrow_addr}")
    print(f"fee bps:  {w3.eth.contract(address=escrow_addr, abi=escrow_abi).functions.feeBps().call()}")

    banner("Buyer mints 1000 test USDC")
    tx = usdc.functions.mint(buyer_acct.address, 1_000_000_000).build_transaction({
        "from": deployer_acct.address,
        "nonce": w3.eth.get_transaction_count(deployer_acct.address),
        "gas": 200_000,
        "gasPrice": w3.eth.gas_price,
    })
    signed = deployer_acct.sign_transaction(tx)
    w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
    print(f"buyer USDC: {usdc.functions.balanceOf(buyer_acct.address).call() / 1e6}")

    banner("SDK happy-path")
    from agentpay import AgentPay
    import agentpay.client as _client
    # hack the SDK to use our test USDC
    _client.USDC_ADDRESSES[w3.eth.chain_id] = usdc_addr

    ap = AgentPay(
        private_key=keys[1].hex() if hasattr(keys[1], "hex") else keys[1],
        escrow_address=escrow_addr,
        chain_id=w3.eth.chain_id,
    )
    # eth-tester needs the provider to be a fresh one bound to the buyer key,
    # so build a new AgentPay with an HTTPProvider pointing at the tester:
    w3_buyer = Web3(EthereumTesterProvider(tester))
    from agentpay.client import AgentPay as _AP
    # rebuild with the same tester provider
    ap.__init__(
        private_key=keys[1] if isinstance(keys[1], str) else _to_hex(keys[1]),
        escrow_address=escrow_addr,
        rpc_url=None,
        chain_id=w3.eth.chain_id,
    )
    # web3.py already has buyer account; re-bind
    ap.w3 = w3_buyer
    ap.account = buyer_acct
    ap.escrow = w3_buyer.eth.contract(address=escrow_addr, abi=escrow_abi)
    ap._usdc = w3_buyer.eth.contract(address=usdc_addr, abi=_client.USDC_ABI)

    task_hash = ap.hash_task("translate-zh-en-1000-words")
    print("step 1: approve + createAndFund for 10 USDC...")
    eid = ap.create_and_fund(
        payee=seller_acct.address,
        amount_usdc=10,
        task_hash=task_hash,
        deadline_hours=1,
    )
    print(f"        escrow id: 0x{eid.hex()}")

    print("step 2: check escrow state")
    e = ap.get_escrow(eid)
    print(f"        status: {e.status} (1=Funded)")
    print(f"        amount: {e.amount/1e6} USDC, fee: {e.fee/1e6} USDC")
    assert e.status == 1
    assert e.amount == 10_000_000
    assert e.fee    == 50_000  # 0.5%

    print("step 3: release")
    ap.release(eid)
    e = ap.get_escrow(eid)
    print(f"        status: {e.status} (2=Released)")
    assert e.status == 2

    seller_bal = usdc.functions.balanceOf(seller_acct.address).call()
    fee_bal    = usdc.functions.balanceOf(fee_acct.address).call()
    buyer_bal  = usdc.functions.balanceOf(buyer_acct.address).call()
    print(f"        seller balance: {seller_bal/1e6} USDC  (expect 9.95)")
    print(f"        fee bal:        {fee_bal/1e6} USDC  (expect 0.05)")
    print(f"        buyer bal:      {buyer_bal/1e6} USDC  (expect 990.00)")
    assert seller_bal == 9_950_000, f"seller wrong: {seller_bal}"
    assert fee_bal    == 50_000,    f"fee wrong: {fee_bal}"
    assert buyer_bal  == 990_000_000

    print("\nstep 4: refund path")
    # a new escrow that will be refunded
    eid2 = ap.create_and_fund(
        payee=seller_acct.address,
        amount_usdc=5,
        task_hash=ap.hash_task("will-be-refunded"),
        deadline_hours=1,
    )
    e = ap.get_escrow(eid2)
    assert e.status == 1
    # fast-forward time: eth-tester doesn't support time travel natively,
    # but refund is allowed for payer/owner any time, so:
    ap.refund(eid2)
    e = ap.get_escrow(eid2)
    print(f"        refund status: {e.status} (3=Refunded)")
    assert e.status == 3

    print("\nALL E2E TESTS PASSED")
    print(f"\ndeployed for your use:")
    print(f"  escrow: {escrow_addr}")
    print(f"  usdc:   {usdc_addr}")
    print(f"  fee:    {fee_acct.address}  (0.5% flows here)")


def _to_hex(k):
    return k.hex() if hasattr(k, "hex") else k


if __name__ == "__main__":
    main()
