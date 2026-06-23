"""Real SDK end-to-end against the live Base Sepolia deployment.

Run with:
    python scripts/sdk/live_demo.py

The deployer key is the public testnet key (already published). The worker key
is generated on first run and stored in .agentpay-data/worker.env so future
runs reuse the same funded EOA.
"""
import os, json, time, secrets
from web3 import Web3
from eth_account import Account

# ---- live config (Base Sepolia) ----
RPC    = os.environ.get("AGENTPAY_RPC", "https://sepolia.base.org")
USDC   = "0x836c5bB361fea411424fF155a08DBa1d4ffE319C"  # MockUSDC (testnet)
VAULT  = "0xB8305f721c95171564544e7a908e60C49F26a63D"
ESCROW = "0xc69505668aadf13d3714bC9884930ce8452ddAf5"
API    = os.environ.get("AGENTPAY_API", "https://disbelief-navy-unhappy.ngrok-free.dev")
USER   = "0x42E1879D715FD337e3C4c085D5C7d030def21cfC"

DEPLOYER_PK = "0xdbd33e8d60a97c392af5094eaf37915a9404c98aed2a0263fd03db1507225e06"
ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.chdir(ROOT)
DATA_DIR = os.path.join(ROOT, ".agentpay-data")
os.makedirs(DATA_DIR, exist_ok=True)
WORKER_ENV = os.path.join(DATA_DIR, "worker.env")

# Reuse a worker key across runs, or generate a fresh EOA on first run.
if os.path.exists(WORKER_ENV):
    WORKER_PK = open(WORKER_ENV).read().splitlines()[0].split("=")[1]
else:
    w3tmp = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 15}))
    for _ in range(50):
        candidate = "0x" + secrets.token_hex(32)
        addr = Account.from_key(candidate).address
        if len(w3tmp.eth.get_code(addr)) == 0 and w3tmp.eth.get_balance(addr) == 0:
            with open(WORKER_ENV, "w") as f:
                f.write(f"WORKER_PK={candidate}\nWORKER_ADDR={addr}\n")
            WORKER_PK = candidate
            break
    else:
        raise RuntimeError("could not find a clean EOA for the worker")

os.chdir(ROOT)

def load_abi(name): return json.loads(open(f"contracts/{name}.abi.json").read())["abi"]

w3 = Web3(Web3.HTTPProvider(RPC, request_kwargs={"timeout": 30}))
deployer = Account.from_key(DEPLOYER_PK)
worker   = Account.from_key(WORKER_PK)

USDC_C = w3.eth.contract(address=USDC,   abi=load_abi("MockUSDC"))
VLT_C  = w3.eth.contract(address=VAULT,  abi=load_abi("AgentPayVault"))
ESC_C  = w3.eth.contract(address=ESCROW, abi=load_abi("AgentPayEscrow"))

# Per-account nonce manager (avoid stale reads on rapid back-to-back txs)
_nonces = {}
def next_nonce(acct):
    n = _nonces.get(acct.address)
    if n is None:
        n = w3.eth.get_transaction_count(acct.address, "pending")
    _nonces[acct.address] = n + 1
    return n

def send(acct, fn, value=0, gas=400_000):
    for attempt in range(4):
        tx = fn.build_transaction({
            "from": acct.address, "nonce": next_nonce(acct),
            "chainId": w3.eth.chain_id, "gas": gas, "gasPrice": w3.eth.gas_price,
            "value": value,
        })
        try: tx["gas"] = w3.eth.estimate_gas({k:v for k,v in tx.items() if k!="gas"})
        except: pass
        try:
            h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
            r = w3.eth.wait_for_transaction_receipt(h, timeout=120)
            assert r.status == 1, f"FAIL: {fn.fn_name}"
            return h
        except Exception as e:
            msg = str(e)
            if "nonce too low" in msg or "already known" in msg or "replacement" in msg:
                # force resync and retry
                _nonces[acct.address] = w3.eth.get_transaction_count(acct.address, "pending")
                time.sleep(0.4)
                continue
            raise
    raise RuntimeError("send: gave up after 4 attempts")

def send_eth(acct, to, value_eth):
    tx = {"to": to, "value": int(value_eth * 1e18), "gas": 21000, "gasPrice": w3.eth.gas_price,
          "nonce": next_nonce(acct), "chainId": w3.eth.chain_id}
    h = w3.eth.send_raw_transaction(acct.sign_transaction(tx).raw_transaction)
    r = w3.eth.wait_for_transaction_receipt(h, timeout=60)
    assert r.status == 1
    return h

def bal(a): return USDC_C.functions.balanceOf(a).call() / 1e6
def ethbal(a): return w3.eth.get_balance(a) / 1e18
def banner(s): print(f"\n\033[36m=== {s} ===\033[0m")

banner("Setup")
if ethbal(worker.address) < 0.001:
    send_eth(deployer, worker.address, 0.002)
print(f"  worker ETH: {ethbal(worker.address):.6f}")
if bal(worker.address) < 100:
    send(deployer, USDC_C.functions.mint(worker.address, 200 * 10**6))
print(f"  worker USDC:  {bal(worker.address):.4f}")
print(f"  user USDC:    {bal(USER):.4f}  (fee recipient)")

from agentpay.client import AgentPay

banner("1. Worker creates SDK client")
ap_worker = AgentPay(
    private_key=WORKER_PK, vault_address=VAULT, escrow_address=ESCROW,
    rpc_url=RPC, chain_id=84532, api_url=API, usdc_address=USDC,
)
print(f"  worker address: {ap_worker.address}")
print(f"  SDK balance:    ${ap_worker.balance():.4f}")

banner("2. Worker browses live tasks via API")
tasks = ap_worker.browse_tasks()[:5]
for t in tasks:
    print(f"  ${t.budget_usdc:>7.2f}  stake=${t.required_stake:>5.2f}  {t.title[:55]}")

banner("3. Worker deposits 50 USDC into vault (earns ~4% APY)")
ap_worker.deposit(usdc=50)
print(f"  vault totalShares: {VLT_C.functions.totalShares().call()/1e6:.4f}")
print(f"  worker USDC left:  {bal(worker.address):.4f}")

banner("4. Buyer posts a task via API")
ap_buyer = AgentPay(
    private_key=DEPLOYER_PK, vault_address=VAULT, escrow_address=ESCROW,
    rpc_url=RPC, chain_id=84532, api_url=API, usdc_address=USDC,
)
task = ap_buyer.post_task(
    title="SDK live demo: write a haiku about USDC",
    description="deliver one haiku (5-7-5) about USDC. submit any text proof.",
    budget_usdc=15, category="writing", deadline_hours=24, required_stake=2,
)
print(f"  task: {task.id}  budget=${task.budget_usdc}  stake=${task.required_stake}")

banner("5. Worker claims with deposit (locks $2 USDC stake)")
claimed = ap_worker.claim_with_deposit(task.id)
print(f"  status: {claimed.status}  claimed_by: {claimed.claimed_by}")

banner("6. Buyer creates + funds on-chain escrow (15 USDC)")
tx = ap_buyer.create_and_fund(
    payee=worker.address, amount_usdc=15,
    task_hash=ap_worker.hash_task(f"agentpay-{task.id}"), deadline_hours=24,
)
print(f"  escrow tx: {tx.hex()[:18]}...")
total = ESC_C.functions.totalEscrows().call()
escrow_id = ESC_C.functions.escrowIds(total - 1).call()
print(f"  escrow id: {escrow_id.hex()[:18]}...")

banner("7. Worker submits work")
sub = ap_worker.submit(task.id, proof="USDC stable, / yield drifts like morning mist, / agents wake and work.")
print(f"  status: {sub.status}")

banner("8. Buyer releases on-chain escrow (worker gets 15 - 0.5% fee)")
send(deployer, ESC_C.functions.release(escrow_id))
esc = ESC_C.functions.getEscrow(escrow_id).call()
print(f"  escrow state: {esc[7]}  (2=Released)")
print(f"  worker USDC:        {bal(worker.address):.4f}  (was 150; expect 164.925)")
print(f"  fee recipient USDC: {bal(USER):.4f}  (was 0.3; expect 0.375)")

banner("9. Buyer settles task via API (records on-chain tx)")
eid_hex = escrow_id.hex() if isinstance(escrow_id, bytes) else escrow_id
settled = ap_buyer.settle_task(task.id, escrow_id=eid_hex, tx_hash=tx.hex())
print(f"  status: {settled.status}  escrow_id: {eid_hex[:18]}...  tx: {tx.hex()[:18]}...")

banner("10. Worker final state via SDK")
print(f"  balance:        ${ap_worker.balance():.4f}")
print(f"  locked_stake:   ${ap_worker.locked_stake():.4f}")
print(f"  apy_estimate:   {ap_worker.apy_estimate():.2%}")
print(f"  api stats:      tasks_settled={ap_worker.stats().get('tasks_settled')}")

print()
print("\033[32m✓ SDK end-to-end against live Base Sepolia deployment complete\033[0m")
