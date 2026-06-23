"""On-chain end-to-end test against the deployed AgentPay on Base Sepolia.

Run after deploy.py:
    python3 scripts/deploy.py --private-key $PK --network base-sepolia --mode mock \\
        --fee-recipient 0x... --yield-recipient 0x...
    python3 scripts/onchain/e2e.py
"""
"""On-chain E2E - v3, with correct escrow id retrieval."""
import json
from pathlib import Path
from web3 import Web3
from eth_account import Account

RPC = "https://base-sepolia-rpc.publicnode.com"
USDC    = Web3.to_checksum_address("0x836c5bB361fea411424fF155a08DBa1d4ffE319C")
AAVE    = Web3.to_checksum_address("0xc743d50550340fc0Dd80B1De99E2a8224E7E9443")
ESCROW  = Web3.to_checksum_address("0xc69505668aadf13d3714bC9884930ce8452ddAf5")
VAULT   = Web3.to_checksum_address("0xB8305f721c95171564544e7a908e60C49F26a63D")
FEE_REC = Web3.to_checksum_address("0x27fe5055144366ec371e0231aa2d7b5f6042b839")

DEPLOYER_PK = "0xdbd33e8d60a97c392af5094eaf37915a9404c98aed2a0263fd03db1507225e06"
WORKER_PK   = "0x" + "a" * 64

ROOT = Path("/Users/sbb/梆梆的文件/知识库/agentpay")
w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
assert w3.is_connected()
deployer = Account.from_key(DEPLOYER_PK)
worker   = Account.from_key(WORKER_PK)
print(f"chain:    {w3.eth.chain_id}")
print(f"deployer: {deployer.address}  bal: {w3.eth.get_balance(deployer.address)/1e18:.6f} ETH")

def load_abi(name): return json.loads((ROOT / f"contracts/{name}.abi.json").read_text())["abi"]
USDC_C = w3.eth.contract(address=USDC,   abi=load_abi("MockUSDC"))
ESC_C  = w3.eth.contract(address=ESCROW, abi=load_abi("AgentPayEscrow"))
VLT_C  = w3.eth.contract(address=VAULT,  abi=load_abi("AgentPayVault"))
A_C    = w3.eth.contract(address=AAVE,   abi=load_abi("mocks/MockAave"))

def send(acct, fn, value=0, gas=400_000):
    tx = fn.build_transaction({
        "from": acct.address, "nonce": w3.eth.get_transaction_count(acct.address),
        "chainId": w3.eth.chain_id, "gas": gas, "gasPrice": w3.eth.gas_price, "value": value,
    })
    try: tx["gas"] = w3.eth.estimate_gas({k:v for k,v in tx.items() if k!="gas"})
    except: pass
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
    if r.status != 1:
        try: w3.eth.call(dict(tx), 'latest')
        except Exception as e: print(f"  REVERT: {e}")
        raise AssertionError(f"tx {fn.fn_name} failed (gas {r.gasUsed})")
    return r, h

def bal(addr): return USDC_C.functions.balanceOf(addr).call() / 1e6

# Top up USDC for a clean run
send(deployer, USDC_C.functions.mint(deployer.address, 1000 * 10**6))

# Approve Escrow
send(deployer, USDC_C.functions.approve(ESCROW, 100 * 10**6))

print(f"\n=== Task 1: createAndFund 25 USDC -> release ===")
n_before = ESC_C.functions.totalEscrows().call()
print(f"  escrow count before: {n_before}")
_, h1 = send(deployer, ESC_C.functions.createAndFund(
    worker.address, USDC, 25 * 10**6, w3.keccak(text="task-1"),
    int(w3.eth.get_block('latest')['timestamp']) + 86400
))
print(f"  tx: {h1.hex()[:18]}...")
escrow_id_1 = ESC_C.functions.escrowIds(n_before).call()
print(f"  escrow_id: {escrow_id_1.hex()[:18]}...")
esc = ESC_C.functions.getEscrow(escrow_id_1).call()
print(f"  getEscrow: payer={esc[0][:10]}.. payee={esc[1][:10]}.. token={esc[2][:10]}.. amt={esc[3]/1e6} state={esc[7]} (1=Funded)")

print(f"\n  Release...")
_, h2 = send(deployer, ESC_C.functions.release(escrow_id_1))
print(f"  tx: {h2.hex()[:18]}...")
esc_after = ESC_C.functions.getEscrow(escrow_id_1).call()
print(f"  after release: state={esc_after[7]} (2=Released)")

print(f"\n=== Task 2: createAndFund 10 USDC -> release ===")
n_before2 = ESC_C.functions.totalEscrows().call()
send(deployer, ESC_C.functions.createAndFund(
    worker.address, USDC, 10 * 10**6, w3.keccak(text="task-2"),
    int(w3.eth.get_block('latest')['timestamp']) + 86400
))
escrow_id_2 = ESC_C.functions.escrowIds(n_before2).call()
print(f"  escrow_id: {escrow_id_2.hex()[:18]}...")
send(deployer, ESC_C.functions.release(escrow_id_2))

print(f"\n=== Task 3: short-deadline + try refund via payer (allowed pre-deadline) ===")
n_before3 = ESC_C.functions.totalEscrows().call()
send(deployer, ESC_C.functions.createAndFund(
    worker.address, USDC, 5 * 10**6, w3.keccak(text="task-3-refund"),
    int(w3.eth.get_block('latest')['timestamp']) + 60
))
escrow_id_3 = ESC_C.functions.escrowIds(n_before3).call()
print(f"  escrow_id: {escrow_id_3.hex()[:18]}...")
send(deployer, ESC_C.functions.refund(escrow_id_3))
esc3 = ESC_C.functions.getEscrow(escrow_id_3).call()
print(f"  after refund: state={esc3[7]} (3=Refunded)")

print(f"\n=== Final state ===")
print(f"  deployer USDC: {bal(deployer.address):.4f}")
print(f"  worker   USDC: {bal(worker.address):.4f}   (expected 24.875 + 9.95 = 34.825)")
print(f"  Vault    USDC: {bal(VAULT):.4f}")
print(f"  Escrow   USDC: {bal(ESCROW):.4f}            (expected 0)")
print(f"  Fee rec  USDC: {bal(FEE_REC):.4f}   (expected 0.125 + 0.05 = 0.175)")
print(f"  Vault.totalShares: {VLT_C.functions.totalShares().call()/1e6:.4f}")
print(f"  Escrow.totalEscrows: {ESC_C.functions.totalEscrows().call()}")

# Validation
expected_worker = 24.875 + 9.95
expected_fee    = 0.125 + 0.05
checks = [
    ("worker 24.875 + 9.95 = 34.825 USDC", abs(bal(worker.address) - expected_worker) < 0.01),
    ("fee 0.125 + 0.05 = 0.175 USDC",     abs(bal(FEE_REC) - expected_fee) < 0.01),
    ("Escrow cleared",                     bal(ESCROW) == 0),
    ("3 escrows created",                  ESC_C.functions.totalEscrows().call() == 3),
]
print(f"\n=== Validation ===")
all_ok = True
for label, ok in checks:
    print(f"  {label}: {'OK ✓' if ok else 'FAIL ✗'}")
    all_ok = all_ok and ok

print(f"\n=== Final deployer ETH ===")
print(f"  {w3.eth.get_balance(deployer.address)/1e18:.6f} ETH (was 0.03)")
print(f"\n{'='*50}")
print(f"OVERALL: {'✓ ALL PASS' if all_ok else '✗ SOME FAILED'}")
print(f"{'='*50}")
