"""Smoke-test the AgentPay SDK against an in-memory EVM.

Proves the SDK can drive the on-chain contracts (deposit, claim_yield,
create_and_fund, release) using its high-level methods.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "sdk" / "python"))


def main():
    from eth_tester import EthereumTester
    from web3 import Web3
    from web3.providers.eth_tester import EthereumTesterProvider
    from eth_account import Account

    tester = EthereumTester()
    w3 = Web3(EthereumTesterProvider(tester))
    keys = [int(k).to_bytes(32, "big") for k in tester.backend.account_keys]
    deployer  = Account.from_key(keys[0])
    buyer     = Account.from_key(keys[1])
    seller    = Account.from_key(keys[2])
    fee_acct  = Account.from_key(keys[3])
    yield_acct = Account.from_key(keys[4])

    def send(acct, fn, gas=500_000):
        tx = fn.build_transaction({"from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
                                   "gas": gas, "gasPrice": w3.eth.gas_price, "chainId": w3.eth.chain_id})
        signed = acct.sign_transaction(tx)
        r = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
        assert r.status == 1, f"tx failed: status={r.status} gas={r.gasUsed}"
        return r

    def deploy(acct, abi, bytecode, *args, gas=3_000_000):
        C = w3.eth.contract(abi=abi, bytecode=bytecode)
        return send(acct, C.constructor(*args), gas=gas).contractAddress

    usdc_d = json.loads(Path(ROOT / "contracts/MockUSDC.abi.json").read_text())
    usdc_addr = deploy(deployer, usdc_d["abi"], usdc_d["bytecode"], gas=2_000_000)
    usdc = w3.eth.contract(address=usdc_addr, abi=usdc_d["abi"])

    aave_d = json.loads(Path(ROOT / "contracts/mocks/MockAave.abi.json").read_text())
    aave_addr = deploy(deployer, aave_d["abi"], aave_d["bytecode"], usdc_addr, gas=3_000_000)
    aave = w3.eth.contract(address=aave_addr, abi=aave_d["abi"])

    escrow_d = json.loads(Path(ROOT / "contracts/AgentPayEscrow.abi.json").read_text())
    escrow_addr = deploy(deployer, escrow_d["abi"], escrow_d["bytecode"],
                         fee_acct.address, 50, gas=3_000_000)
    vault_d = json.loads(Path(ROOT / "contracts/AgentPayVault.abi.json").read_text())
    vault_addr = deploy(deployer, vault_d["abi"], vault_d["bytecode"],
                        usdc_addr, aave_addr, yield_acct.address, gas=3_000_000)
    send(deployer, aave.functions.setVault(vault_addr), gas=200_000)
    vault = w3.eth.contract(address=vault_addr, abi=vault_d["abi"])
    send(deployer, vault.functions.init(), gas=500_000)
    send(deployer, vault.functions.setTaskManager(escrow_addr), gas=200_000)

    from agentpay import AgentPay, USDC_ABI, ESCROW_ABI, VAULT_ABI

    class _FakePay(AgentPay):
        def __init__(self, key, vault_addr, escrow_addr, usdc_addr):
            self.account = Account.from_key(key)
            self.w3 = w3
            self.vault_address = vault_addr
            self.escrow_address = escrow_addr
            self._usdc = w3.eth.contract(address=usdc_addr, abi=USDC_ABI)
            self.vault  = w3.eth.contract(address=vault_addr,  abi=VAULT_ABI)
            self.escrow = w3.eth.contract(address=escrow_addr, abi=ESCROW_ABI)
            self.chain_id = w3.eth.chain_id
            self.api_url = ""
            self.api_key = None

    seller_pay = _FakePay(keys[2], vault_addr, escrow_addr, usdc_addr)
    buyer_pay  = _FakePay(keys[1], vault_addr, escrow_addr, usdc_addr)

    send(deployer, usdc.functions.mint(buyer.address, 1_000_000_000))
    send(deployer, usdc.functions.mint(seller.address, 1_000_000_000))

    print("\n[1] seller.deposit(100)  # high-level SDK call")
    seller_pay.deposit(100)
    bal = seller_pay.balance()
    print(f"    vault balance: {bal} USDC")
    assert bal == 100.0, f"expected 100.0, got {bal}"

    print("\n[2] aave.accrueYield(4) + seller.claim_yield()")
    send(deployer, usdc.functions.mint(aave_addr, 4_000_000), gas=200_000)
    send(deployer, aave.functions.accrueYield(4_000_000), gas=200_000)
    seller_pay.claim_yield()
    ybal = usdc.functions.balanceOf(yield_acct.address).call()
    print(f"    yield recipient got: {ybal/1e6} USDC  (expect 1.2)")
    assert ybal == 1_200_000

    print("\n[3] buyer.create_and_fund(seller, 10) + buyer.release()")
    task_hash = AgentPay.hash_task("write-a-haiku")
    eid = buyer_pay.create_and_fund(
        payee=seller.address, amount_usdc=10, task_hash=task_hash, deadline_hours=24,
    )
    print(f"    escrow id: 0x{eid.hex()[:16]}...")
    seller_before = usdc.functions.balanceOf(seller.address).call()
    buyer_pay.release(eid)
    seller_after = usdc.functions.balanceOf(seller.address).call()
    net = (seller_after - seller_before) / 1e6
    print(f"    seller received: {net} USDC  (expect 9.95)")
    assert abs(net - 9.95) < 0.01

    print("\n[4] fee recipient got 0.05 USDC")
    fbal = usdc.functions.balanceOf(fee_acct.address).call()
    print(f"    fee recipient: {fbal/1e6} USDC")
    assert fbal == 50_000

    print("\n\033[32m=== SDK SMOKE TEST PASSED ===\033[0m")


if __name__ == "__main__":
    main()
