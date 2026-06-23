"""End-to-end test: full happy path for Escrow and Vault.

Uses eth-tester (in-memory EVM) — no Anvil needed.
"""
from __future__ import annotations

import json
import subprocess
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def banner(s):
    print(f"\n\033[36m=== {s} ===\033[0m")


def main():
    try:
        from eth_tester import EthereumTester
        from web3 import Web3
        from web3.providers.eth_tester import EthereumTesterProvider
        from eth_account import Account
    except ImportError:
        print("install: pip install 'web3>=6.0' eth-tester eth-account")
        return 1

    banner("Spinning up in-memory EVM")
    tester = EthereumTester()
    w3 = Web3(EthereumTesterProvider(tester))
    keys = tester.backend.account_keys
    deployer = Account.from_key(keys[0])
    buyer    = Account.from_key(keys[1])
    seller   = Account.from_key(keys[2])
    fee_acct = Account.from_key(keys[3])
    yield_acct = Account.from_key(keys[4])
    print(f"chain id: {w3.eth.chain_id}")

    def send(acct, fn, gas=500_000, value=0):
        tx = fn.build_transaction({
            "from": acct.address,
            "nonce": w3.eth.get_transaction_count(acct.address),
            "gas": gas,
            "gasPrice": w3.eth.gas_price,
            "value": value,
        })
        signed = acct.sign_transaction(tx)
        r = w3.eth.wait_for_transaction_receipt(w3.eth.send_raw_transaction(signed.raw_transaction))
        assert r.status == 1, f"tx failed: {r}"
        return r

    def deploy(acct, abi, bytecode, *args, gas=3_000_000):
        Contract = w3.eth.contract(abi=abi, bytecode=bytecode)
        return send(acct, Contract.constructor(*args), gas=gas).contractAddress

    # ----- mock USDC -----
    banner("Deploying MockUSDC")
    mock_data = json.loads(Path(ROOT / "contracts/MockUSDC.abi.json").read_text())
    usdc_addr = deploy(deployer, mock_data["abi"], mock_data["bytecode"])
    usdc = w3.eth.contract(address=usdc_addr, abi=mock_data["abi"])
    print(f"  {usdc_addr}")

    # ----- mock Aave (precompiled) -----
    banner("Deploying MockAave")
    aave_abi = json.loads(open("/tmp/mock-aave-v3/_tmp_MockAave_sol_MockAave.abi").read())
    aave_bin = open("/tmp/mock-aave-v3/_tmp_MockAave_sol_MockAave.bin").read().strip()
    aave_addr = deploy(deployer, aave_abi, aave_bin, usdc_addr)
    aave = w3.eth.contract(address=aave_addr, abi=aave_abi)
    print(f"  {aave_addr}")

    # ----- escrow -----
    banner("Deploying AgentPayEscrow")
    escrow_abi = json.loads(Path(ROOT / "contracts/AgentPayEscrow.abi.json").read_text())
    escrow_bin = next(ROOT.glob("build/*AgentPayEscrow*.bin")).read_text().strip()
    escrow_addr = deploy(deployer, escrow_abi, escrow_bin, fee_acct.address, 50)
    escrow = w3.eth.contract(address=escrow_addr, abi=escrow_abi)
    print(f"  {escrow_addr}  feeBps: {escrow.functions.feeBps().call()}")

    # ----- vault -----
    banner("Deploying AgentPayVault")
    vault_data = json.loads(Path(ROOT / "contracts/AgentPayVault.abi.json").read_text())
    vault_abi = vault_data["abi"]
    vault_bin = vault_data["bytecode"]
    vault_addr = deploy(deployer, vault_abi, vault_bin, usdc_addr, aave_addr, yield_acct.address)
    vault = w3.eth.contract(address=vault_addr, abi=vault_abi)
    send(deployer, aave.functions.setVault(vault_addr))
    send(deployer, vault.functions.init())
    print(f"  {vault_addr}  aUsdc: {vault.functions.aUsdc().call()}  skimBps: {vault.functions.yieldSkimBps().call()}")

    # ----- mint USDC -----
    banner("Minting 1000 USDC to buyer")
    send(deployer, usdc.functions.mint(buyer.address, 1_000_000_000))
    print(f"  buyer USDC: {usdc.functions.balanceOf(buyer.address).call() / 1e6}")

    # ----- escrow: fund + release -----
    banner("Escrow happy path")
    send(buyer, usdc.functions.approve(escrow_addr, 10_000_000))
    task_hash = b"\x42" * 32
    deadline = int(time.time()) + 3600
    r = send(buyer, escrow.functions.createAndFund(seller.address, usdc_addr, 10_000_000, task_hash, deadline), gas=600_000)
    eid = escrow.events.EscrowCreated().process_receipt(r)[0]["args"]["id"]
    print(f"  escrow id: 0x{eid.hex()[:16]}...")

    e = escrow.functions.getEscrow(eid).call()
    print(f"  status: {e[7]} (1=Funded), amount: {e[3]/1e6}, fee: {e[4]/1e6}")
    assert e[7] == 1 and e[3] == 10_000_000 and e[4] == 50_000

    send(buyer, escrow.functions.release(eid), gas=200_000)
    seller_bal = usdc.functions.balanceOf(seller.address).call()
    fee_bal    = usdc.functions.balanceOf(fee_acct.address).call()
    print(f"  after release: seller={seller_bal/1e6}, fee={fee_bal/1e6}")
    assert seller_bal == 9_950_000
    assert fee_bal == 50_000
    print("  \033[32mPASS\033[0m")

    # ----- escrow: refund -----
    banner("Escrow refund path")
    send(buyer, usdc.functions.approve(escrow_addr, 5_000_000))
    r = send(buyer, escrow.functions.createAndFund(seller.address, usdc_addr, 5_000_000, b"\x43" * 32, deadline), gas=600_000)
    eid2 = escrow.events.EscrowCreated().process_receipt(r)[0]["args"]["id"]
    buyer_before = usdc.functions.balanceOf(buyer.address).call()
    send(buyer, escrow.functions.refund(eid2), gas=200_000)
    buyer_after = usdc.functions.balanceOf(buyer.address).call()
    print(f"  refunded: {(buyer_after - buyer_before)/1e6} USDC")
    assert buyer_after - buyer_before == 5_000_000
    print("  \033[32mPASS\033[0m")

    # ----- vault: deposit + yield + skim -----
    banner("Vault deposit + yield + skim path")
    send(buyer, usdc.functions.approve(vault_addr, 100_000_000))
    send(buyer, vault.functions.deposit(100_000_000), gas=400_000)
    bal = vault.functions.aTokenBalanceOf(buyer.address).call()
    print(f"  deposited; vault balance: {bal/1e6}")
    assert bal == 100_000_000

    # simulate 4 USDC yield: mint to aave, call accrueYield
    send(deployer, usdc.functions.mint(aave_addr, 4_000_000))
    send(deployer, aave.functions.accrueYield(4_000_000), gas=200_000)
    bal2 = vault.functions.aTokenBalanceOf(buyer.address).call()
    print(f"  after 4% yield: {bal2/1e6}")
    assert bal2 == 104_000_000

    yield_before = usdc.functions.balanceOf(yield_acct.address).call()
    send(deployer, vault.functions.skimYield(), gas=400_000)
    yield_after = usdc.functions.balanceOf(yield_acct.address).call()
    skimmed = yield_after - yield_before
    print(f"  skimmed to yield recipient: {skimmed/1e6} USDC (expect 1.2 = 30% of 4)")
    assert skimmed == 1_200_000
    print("  \033[32mPASS\033[0m")

    print("\n\033[32m=== ALL E2E TESTS PASSED ===\033[0m")
    print(f"\nContracts deployed in-memory:")
    print(f"  MockUSDC:  {usdc_addr}")
    print(f"  MockAave:  {aave_addr}")
    print(f"  Escrow:    {escrow_addr}")
    print(f"  Vault:     {vault_addr}")
    return 0


if __name__ == "__main__":
    import sys
    sys.exit(main() or 0)
