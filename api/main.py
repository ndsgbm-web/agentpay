"""AgentPay coordination service.

Indexes on-chain vault + escrow events, hosts the task board, and
serves platform stats. Off-chain coordination; contracts are the
single source of truth for funds.
"""
from __future__ import annotations

import json
import os
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Optional

from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

DATA_DIR = Path(os.environ.get("AGENTPAY_DATA", "./.agentpay-data"))
DATA_DIR.mkdir(parents=True, exist_ok=True)
TASKS_FILE = DATA_DIR / "tasks.json"
STATS_FILE = DATA_DIR / "stats.json"


def _load_json(path: Path, default):
    if not path.exists():
        return default
    try:
        return json.loads(path.read_text())
    except Exception:
        return default


def _save_json(path: Path, data) -> None:
    path.write_text(json.dumps(data, indent=2, default=str))


# ---------- models ----------

class Task(BaseModel):
    id: str = Field(default_factory=lambda: uuid.uuid4().hex[:16])
    title: str
    description: str
    category: str = "general"
    budget_usdc: float
    deadline_hours: int = 24
    required_stake: float = 0.0
    buyer_address: str
    created_at: int = Field(default_factory=lambda: int(time.time()))
    status: str = "open"          # open | claimed | submitted | settled | refunded | slashed
    claimed_by: Optional[str] = None
    submitted_proof: Optional[str] = None
    escrow_id: Optional[str] = None
    tx_hash: Optional[str] = None
    source: str = "agentpay-direct"
    external_id: str = ""
    url: str = ""


class TaskCreate(BaseModel):
    title: str
    description: str
    category: str = "general"
    budget_usdc: float
    deadline_hours: int = 24
    required_stake: float = 0.0
    buyer_address: str
    source: str = "agentpay-direct"
    external_id: str = ""
    url: str = ""


class ClaimRequest(BaseModel):
    seller_address: str


class SubmitRequest(BaseModel):
    seller_address: str
    proof: str


class SlashRequest(BaseModel):
    caller: str
    reason: str = ""


class ScrapedTaskIngest(BaseModel):
    """Used by scrapers to push tasks into the pool."""
    source: str
    external_id: str
    title: str
    description: str
    category: str = "general"
    budget_usdc: float
    buyer_address: str = ""
    deadline_hours: int = 168
    url: str = ""
    required_stake: float = 0.0


class VaultEvent(BaseModel):
    kind: str                  # deposit | withdraw | stake_locked | stake_released | stake_slashed | yield_skimmed
    agent: str
    amount: Optional[int] = None
    tx_hash: str
    chain_id: int = 8453
    timestamp: int = Field(default_factory=lambda: int(time.time()))
    extra: dict = Field(default_factory=dict)


class EscrowEvent(BaseModel):
    kind: str                  # created | funded | released | refunded
    escrow_id: str
    tx_hash: str
    payer: Optional[str] = None
    payee: Optional[str] = None
    amount: Optional[int] = None
    fee: Optional[int] = None
    chain_id: int = 8453
    timestamp: int = Field(default_factory=lambda: int(time.time()))


@asynccontextmanager
async def lifespan(app: FastAPI):
    if not STATS_FILE.exists():
        _save_json(STATS_FILE, {
            "total_escrows": 0,
            "total_volume_usdc": 0.0,
            "total_fees_usdc": 0.0,
            "tasks_posted": 0,
            "tasks_settled": 0,
            "tasks_slashed": 0,
            "total_deposits_usdc": 0.0,
            "total_slashed_usdc": 0.0,
        })
    yield


app = FastAPI(
    title="AgentPay",
    description="USDC collateral pool + task market for AI agents",
    version="0.2.0",
    lifespan=lifespan,
)
app.add_middleware(
    CORSMiddleware, allow_origins=["*"], allow_methods=["*"], allow_headers=["*"],
)

WEB_DIR = Path(__file__).resolve().parent.parent / "web"
if WEB_DIR.exists():
    app.mount("/static", StaticFiles(directory=str(WEB_DIR)), name="static")


@app.get("/")
async def root():
    idx = WEB_DIR / "index.html"
    if idx.exists():
        return FileResponse(str(idx))
    return {"name": "AgentPay", "version": "0.2.0"}


@app.get("/health")
async def health():
    return {"status": "ok", "ts": int(time.time())}


# ---------- task board ----------

@app.get("/tasks")
async def list_tasks(
    status: Optional[str] = None,
    category: Optional[str] = None,
    source: Optional[str] = None,
    limit: int = 100,
):
    tasks = _load_json(TASKS_FILE, [])
    out = tasks
    if status:   out = [t for t in out if t.get("status") == status]
    if category: out = [t for t in out if t.get("category") == category]
    if source:   out = [t for t in out if t.get("source") == source]
    return {"tasks": out[-limit:], "count": min(len(out), limit)}


@app.post("/tasks")
async def create_task(req: TaskCreate):
    if req.budget_usdc <= 0:
        raise HTTPException(400, "budget_usdc must be > 0")
    task = Task(**req.model_dump())
    tasks = _load_json(TASKS_FILE, [])
    tasks.append(task.model_dump())
    _save_json(TASKS_FILE, tasks)
    stats = _load_json(STATS_FILE, {})
    stats["tasks_posted"] = stats.get("tasks_posted", 0) + 1
    _save_json(STATS_FILE, stats)
    return task


def _agent_locked_stake(address: str) -> float:
    """Sum of USDC the agent has currently staked/locked in the vault."""
    events = DATA_DIR / "vault_events.jsonl"
    if not events.exists():
        return 0.0
    locked = 0.0
    for line in events.open():
        try:
            e = json.loads(line)
        except Exception:
            continue
        if e.get("agent", "").lower() != address.lower():
            continue
        if e.get("kind") == "stake_locked" and e.get("amount") is not None:
            locked += e["amount"] / 1_000_000
        elif e.get("kind") == "stake_released" and e.get("amount") is not None:
            locked -= e["amount"] / 1_000_000
        elif e.get("kind") == "stake_slashed" and e.get("amount") is not None:
            locked -= e["amount"] / 1_000_000
    return max(0.0, locked)


@app.post("/tasks/ingest")
async def ingest_scraped(req: ScrapedTaskIngest):
    """Scraper pushes a batch of tasks into the pool."""
    if req.budget_usdc <= 0:
        raise HTTPException(400, "budget_usdc must be > 0")
    # dedupe by (source, external_id); also collapse empty external_ids by title+url
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if t.get("status") != "open":
            continue
        same_source = t.get("source") == req.source
        same_id = req.external_id and t.get("external_id") == req.external_id
        same_title = t.get("title") == req.title and t.get("url") == req.url
        if same_source and (same_id or (same_title and not req.external_id)):
            return {"ok": True, "id": t["id"], "duplicate": True}
    task = Task(
        title=req.title, description=req.description,
        category=req.category, budget_usdc=req.budget_usdc,
        deadline_hours=req.deadline_hours, buyer_address=req.buyer_address,
        source=req.source, external_id=req.external_id, url=req.url,
        required_stake=req.required_stake,
    )
    tasks.append(task.model_dump())
    _save_json(TASKS_FILE, tasks)
    stats = _load_json(STATS_FILE, {})
    stats["tasks_posted"] = stats.get("tasks_posted", 0) + 1
    _save_json(STATS_FILE, stats)
    return {"ok": True, "id": task.id, "duplicate": False}


@app.get("/tasks/{task_id}")
async def get_task(task_id: str):
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if t["id"] == task_id:
            return t
    raise HTTPException(404, "task not found")


@app.post("/tasks/{task_id}/claim")
async def claim_task(task_id: str, req: ClaimRequest):
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if t["id"] == task_id:
            if t["status"] != "open":
                raise HTTPException(409, f"task is {t['status']}")
            # Stake gate: if the task has required_stake > 0, the agent
            # must already have that much USDC locked in the vault.
            stake_needed = float(t.get("required_stake", 0) or 0)
            if stake_needed > 0:
                have = _agent_locked_stake(req.seller_address)
                if have < stake_needed:
                    raise HTTPException(
                        402,
                        f"deposit required: stake {stake_needed} USDC in vault (have {have});"
                        f" call vault.lockStake() on-chain or POST /agents/{req.seller_address}/stake",
                    )
            t["status"] = "claimed"
            t["claimed_by"] = req.seller_address
            _save_json(TASKS_FILE, tasks)
            return t
    raise HTTPException(404, "task not found")


class StakeRequest(BaseModel):
    amount_usdc: float
    task_id: str = ""
    tx_hash: str = ""


@app.post("/agents/{address}/stake")
async def deposit_stake(address: str, req: StakeRequest):
    """Off-chain bookkeeping for an agent's vault stake. The actual
    USDC transfer happens on-chain (vault.lockStake); this endpoint
    just lets the API know the agent has skin in the game so it can
    clear the claim gate.
    """
    amount_usdc = req.amount_usdc
    task_id = req.task_id
    if amount_usdc <= 0:
        raise HTTPException(400, "amount_usdc must be > 0")
    evt = VaultEvent(
        kind="stake_locked",
        agent=address,
        amount=int(round(amount_usdc * 1_000_000)),
        tx_hash=req.tx_hash or "",
        extra={"task_id": task_id} if task_id else {},
    )
    events_file = DATA_DIR / "vault_events.jsonl"
    with events_file.open("a") as f:
        f.write(json.dumps(evt.model_dump()) + chr(10))
    return {"ok": True, "locked_usdc": amount_usdc, "agent": address}


@app.post("/tasks/{task_id}/submit")
async def submit_task(task_id: str, req: SubmitRequest):
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if t["id"] == task_id:
            if t["status"] != "claimed":
                raise HTTPException(409, f"task is {t['status']}")
            if t.get("claimed_by") != req.seller_address:
                raise HTTPException(403, "not the claimed seller")
            t["status"] = "submitted"
            t["submitted_proof"] = req.proof
            _save_json(TASKS_FILE, tasks)
            return t
    raise HTTPException(404, "task not found")


@app.post("/tasks/{task_id}/settle")
async def settle_task(task_id: str, escrow_id: str, tx_hash: str):
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if t["id"] == task_id:
            t["status"] = "settled"
            t["escrow_id"] = escrow_id
            t["tx_hash"] = tx_hash
            _save_json(TASKS_FILE, tasks)
            stats = _load_json(STATS_FILE, {})
            stats["tasks_settled"] = stats.get("tasks_settled", 0) + 1
            stats["total_volume_usdc"] = stats.get("total_volume_usdc", 0.0) + t["budget_usdc"]
            _save_json(STATS_FILE, stats)
            return t
    raise HTTPException(404, "task not found")


@app.post("/tasks/{task_id}/slash")
async def slash_task(task_id: str, req: SlashRequest):
    """Buyer (or owner) slashes the agent's stake on failure / timeout."""
    tasks = _load_json(TASKS_FILE, [])
    for t in tasks:
        if t["id"] == task_id:
            if t.get("buyer_address") != req.caller:
                raise HTTPException(403, "only the buyer can slash")
            t["status"] = "slashed"
            _save_json(TASKS_FILE, tasks)
            stats = _load_json(STATS_FILE, {})
            stats["tasks_slashed"] = stats.get("tasks_slashed", 0) + 1
            stats["total_slashed_usdc"] = stats.get("total_slashed_usdc", 0.0) + t.get("required_stake", 0)
            _save_json(STATS_FILE, stats)
            return t
    raise HTTPException(404, "task not found")


# ---------- on-chain event indexer ----------

@app.post("/events/escrow")
async def report_escrow_event(evt: EscrowEvent):
    events_file = DATA_DIR / "escrow_events.jsonl"
    with events_file.open("a") as f:
        f.write(json.dumps(evt.model_dump()) + "\n")
    stats = _load_json(STATS_FILE, {})
    if evt.kind == "released" and evt.fee is not None:
        stats["total_fees_usdc"] = stats.get("total_fees_usdc", 0.0) + evt.fee / 1_000_000
    _save_json(STATS_FILE, stats)
    return {"ok": True}


@app.post("/events/vault")
async def report_vault_event(evt: VaultEvent):
    events_file = DATA_DIR / "vault_events.jsonl"
    with events_file.open("a") as f:
        f.write(json.dumps(evt.model_dump()) + "\n")
    stats = _load_json(STATS_FILE, {})
    if evt.kind == "deposit" and evt.amount is not None:
        stats["total_deposits_usdc"] = stats.get("total_deposits_usdc", 0.0) + evt.amount / 1_000_000
    if evt.kind == "stake_slashed" and evt.amount is not None:
        stats["total_slashed_usdc"] = stats.get("total_slashed_usdc", 0.0) + evt.amount / 1_000_000
    _save_json(STATS_FILE, stats)
    return {"ok": True}


@app.get("/agents/{address}")
async def agent_profile(address: str):
    """Public profile for an agent: balance, tasks completed, slash count."""
    vault_events = DATA_DIR / "vault_events.jsonl"
    escrow_events = DATA_DIR / "escrow_events.jsonl"

    deposits = 0.0
    withdrawals = 0.0
    staked = 0.0
    slashed = 0
    released_to = 0.0
    paid_out = 0.0

    if vault_events.exists():
        for line in vault_events.open():
            try:
                e = json.loads(line)
                if e.get("agent", "").lower() != address.lower():
                    continue
                amt = (e.get("amount") or 0) / 1_000_000
                kind = e.get("kind")
                if kind == "deposit" and amt:
                    deposits += amt
                elif kind == "withdraw" and amt:
                    withdrawals += amt
                elif kind == "stake_locked" and amt:
                    staked += amt
                elif kind == "stake_released" and amt:
                    staked -= amt
                elif kind == "stake_slashed" and amt:
                    staked -= amt
                    slashed += 1
            except Exception:
                continue
    staked = max(0.0, staked)

    tasks = _load_json(TASKS_FILE, [])
    completed = sum(1 for t in tasks if t.get("claimed_by", "").lower() == address.lower() and t.get("status") == "settled")
    failed    = sum(1 for t in tasks if t.get("claimed_by", "").lower() == address.lower() and t.get("status") == "slashed")

    return {
        "address": address,
        "deposited_usdc": round(deposits, 4),
        "withdrawn_usdc": round(withdrawals, 4),
        "staked_usdc": round(staked, 4),
        "tasks_completed": completed,
        "tasks_failed": failed,
        "stake_slashed_count": slashed,
    }


# ---------- stats ----------

@app.get("/stats")
async def stats():
    s = _load_json(STATS_FILE, {})
    tasks = _load_json(TASKS_FILE, [])
    s["open_tasks"]      = sum(1 for t in tasks if t.get("status") == "open")
    s["claimed_tasks"]   = sum(1 for t in tasks if t.get("status") == "claimed")
    s["submitted_tasks"] = sum(1 for t in tasks if t.get("status") == "submitted")
    s["settled_tasks"]   = sum(1 for t in tasks if t.get("status") == "settled")
    s["slashed_tasks"]   = sum(1 for t in tasks if t.get("status") == "slashed")
    s["total_tasks"]     = len(tasks)

    # group tasks by source
    by_source = {}
    for t in tasks:
        src = t.get("source", "unknown")
        by_source[src] = by_source.get(src, 0) + 1
    s["tasks_by_source"] = by_source
    return s
