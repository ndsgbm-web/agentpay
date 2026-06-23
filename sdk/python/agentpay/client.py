"""AgentPay client — USDC collateral pool + task market for AI agents."""
from __future__ import annotations

try:
    from web3 import Web3
except ImportError:
    Web3 = None

import hashlib
import json
import os
import time
import urllib.request
from dataclasses import dataclass
from typing import Optional

# USDC contract addresses (Circle official)
USDC_ADDRESSES = {
    8453:  "0x833589fCD6eDb6E08f4c7C32D4f71b54bdA02913",  # Base mainnet
    84532: "0x036CbD53842c5426634e7929541eC2318f3dCF7e",  # Base Sepolia
    1:     "0xA0b86991c6218b36c1d19D4a2e9Eb0cE3606eB48",  # Ethereum mainnet
    137:   "0x3c499c542cEF5E3811e1192ce70d8cC03d5c3359",  # Polygon
    42161: "0xaf88d065e77c8cC2239327C5EDb3A432268e5831",  # Arbitrum One
}

# Minimal Aave v3 Pool address on Base mainnet
AAVE_POOL_BASE = "0xA238Dd80C259a72e81d7e4664a9801593F98d1c5"

VAULT_ABI = json.loads(
    (Path := __import__("pathlib").Path(__file__).resolve().parent.parent.parent
     .joinpath("contracts", "AgentPayVault.abi.json")).read_text()
)["abi"] if False else None  # lazy; we'll load lazily in init

ESCROW_ABI = [
    {"type": "function", "name": "createAndFund",
     "inputs": [
        {"name": "payee", "type": "address"},
        {"name": "token", "type": "address"},
        {"name": "amount", "type": "uint256"},
        {"name": "taskHash", "type": "bytes32"},
        {"name": "deadline", "type": "uint64"},
     ],
     "outputs": [{"name": "id", "type": "bytes32"}],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "release",
     "inputs": [{"name": "id", "type": "bytes32"}],
     "outputs": [],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "refund",
     "inputs": [{"name": "id", "type": "bytes32"}],
     "outputs": [],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "getEscrow",
     "inputs": [{"name": "id", "type": "bytes32"}],
     "outputs": [{
         "name": "", "type": "tuple",
         "components": [
             {"name": "payer", "type": "address"},
             {"name": "payee", "type": "address"},
             {"name": "token", "type": "address"},
             {"name": "amount", "type": "uint256"},
             {"name": "fee", "type": "uint256"},
             {"name": "taskHash", "type": "bytes32"},
             {"name": "deadline", "type": "uint64"},
             {"name": "status", "type": "uint8"},
         ]
     }],
     "stateMutability": "view"},
    {"type": "function", "name": "feeBps",
     "inputs": [], "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view"},
]

USDC_ABI = [
    {"type": "function", "name": "approve",
     "inputs": [
        {"name": "spender", "type": "address"},
        {"name": "amount", "type": "uint256"},
     ],
     "outputs": [{"name": "", "type": "bool"}],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "balanceOf",
     "inputs": [{"name": "account", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view"},
    {"type": "function", "name": "decimals",
     "inputs": [],
     "outputs": [{"name": "", "type": "uint8"}],
     "stateMutability": "view"},
]

VAULT_ABI = [
    {"type": "function", "name": "deposit",
     "inputs": [{"name": "usdcAmount", "type": "uint256"}],
     "outputs": [{"name": "aTokensOut", "type": "uint256"}],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "withdraw",
     "inputs": [{"name": "usdcAmount", "type": "uint256"}],
     "outputs": [{"name": "aTokensBurned", "type": "uint256"}],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "aTokenBalanceOf",
     "inputs": [{"name": "agent", "type": "address"}],
     "outputs": [{"name": "", "type": "uint256"}],
     "stateMutability": "view"},
    {"type": "function", "name": "lockStake",
     "inputs": [
        {"name": "agent", "type": "address"},
        {"name": "usdcAmount", "type": "uint256"},
        {"name": "taskId", "type": "bytes32"},
     ],
     "outputs": [],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "releaseStake",
     "inputs": [
        {"name": "agent", "type": "address"},
        {"name": "usdcAmount", "type": "uint256"},
        {"name": "taskId", "type": "bytes32"},
     ],
     "outputs": [],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "slash",
     "inputs": [
        {"name": "agent", "type": "address"},
        {"name": "to", "type": "address"},
        {"name": "usdcAmount", "type": "uint256"},
        {"name": "taskId", "type": "bytes32"},
     ],
     "outputs": [],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "skimYield",
     "inputs": [], "outputs": [],
     "stateMutability": "nonpayable"},
    {"type": "function", "name": "positions",
     "inputs": [{"name": "", "type": "address"}],
     "outputs": [{
        "name": "", "type": "tuple",
        "components": [
            {"name": "aTokenShares", "type": "uint256"},
            {"name": "lockedStake", "type": "uint256"},
            {"name": "yieldDebt", "type": "uint256"},
        ],
     }],
     "stateMutability": "view"},
    {"type": "event", "name": "Deposit",
     "inputs": [
        {"indexed": True, "name": "agent", "type": "address"},
        {"indexed": False, "name": "usdcAmount", "type": "uint256"},
        {"indexed": False, "name": "aTokens", "type": "uint256"},
     ],
     "anonymous": False},
    {"type": "event", "name": "StakeLocked",
     "inputs": [
        {"indexed": True, "name": "agent", "type": "address"},
        {"indexed": False, "name": "amount", "type": "uint256"},
        {"indexed": True, "name": "taskId", "type": "bytes32"},
     ],
     "anonymous": False},
    {"type": "event", "name": "StakeSlashed",
     "inputs": [
        {"indexed": True, "name": "agent", "type": "address"},
        {"indexed": True, "name": "to", "type": "address"},
        {"indexed": False, "name": "amount", "type": "uint256"},
        {"indexed": True, "name": "taskId", "type": "bytes32"},
     ],
     "anonymous": False},
]


@dataclass
class Task:
    id: str
    title: str
    description: str
    category: str
    budget_usdc: float
    deadline_hours: int
    buyer_address: str
    status: str
    source: str = ""
    external_id: str = ""
    required_stake: float = 0.0
    url: str = ""
    claimed_by: Optional[str] = None

    @classmethod
    def from_dict(cls, d: dict) -> "Task":
        return cls(
            id=d.get("id", ""),
            title=d.get("title", ""),
            description=d.get("description", ""),
            category=d.get("category", "general"),
            budget_usdc=float(d.get("budget_usdc", 0)),
            deadline_hours=int(d.get("deadline_hours", 24)),
            buyer_address=d.get("buyer_address", ""),
            status=d.get("status", "open"),
            source=d.get("source", ""),
            external_id=d.get("external_id", ""),
            required_stake=float(d.get("required_stake", 0)),
            url=d.get("url", ""),
            claimed_by=d.get("claimed_by"),
        )


class AgentPay:
    """USDC collateral pool + task market client for AI agents."""

    DEFAULT_RPCS = {
        8453:  "https://mainnet.base.org",
        84532: "https://sepolia.base.org",
        1:     "https://eth.llamarpc.com",
        137:   "https://polygon-rpc.com",
        42161: "https://arb1.arbitrum.io/rpc",
    }
    DEFAULT_API = "https://api.agentpay.xyz"
    DEFAULT_AAVE_POOL = AAVE_POOL_BASE

    def __init__(
        self,
        private_key: Optional[str] = None,
        vault_address: Optional[str] = None,
        escrow_address: Optional[str] = None,
        rpc_url: Optional[str] = None,
        chain_id: int = 8453,
        api_url: Optional[str] = None,
        api_key: Optional[str] = None,
        aave_pool: Optional[str] = None,
    ):
        self.chain_id = chain_id
        self.api_url = (api_url or os.environ.get("AGENTPAY_API") or self.DEFAULT_API).rstrip("/")
        self.api_key = api_key
        self.vault_address = vault_address
        self.escrow_address = escrow_address
        self.w3 = None
        self.account = None
        self.vault = None
        self.escrow = None
        self._usdc = None

        if private_key is not None:
            try:
                from eth_account import Account
            except ImportError as e:
                raise ImportError("agentpay requires web3.py: pip install 'web3>=6.0' eth-account") from e

            self.w3 = Web3(Web3.HTTPProvider(
                rpc_url or self.DEFAULT_RPCS.get(chain_id, ""),
                request_kwargs={"timeout": 30},
            ))
            if not self.w3.is_connected():
                raise RuntimeError(f"cannot reach RPC for chain_id={chain_id}")
            self.account = Account.from_key(private_key)
            self._usdc = self.w3.eth.contract(address=self.usdc(), abi=USDC_ABI)
            if vault_address:
                self.vault_address = Web3.to_checksum_address(vault_address)
                self.vault = self.w3.eth.contract(address=self.vault_address, abi=VAULT_ABI)
            if escrow_address:
                self.escrow_address = Web3.to_checksum_address(escrow_address)
                self.escrow = self.w3.eth.contract(address=self.escrow_address, abi=ESCROW_ABI)

    # ---------- helpers ----------

    @property
    def address(self) -> Optional[str]:
        return self.account.address if self.account else None

    @staticmethod
    def hash_task(task: str) -> bytes:
        return hashlib.sha256(task.encode("utf-8")).digest()

    @staticmethod
    def to_usdc(amount: float) -> int:
        return int(round(amount * 1_000_000))

    @staticmethod
    def from_usdc(units: int) -> float:
        return units / 1_000_000

    def usdc(self) -> str:
        # If a USDC contract was bound via __init__ (e.g. mock tests), use that.
        if self._usdc is not None:
            try:
                return self._usdc.address
            except AttributeError:
                pass
        return USDC_ADDRESSES[self.chain_id]

    # ---------- low-level tx ----------

    def _send(self, fn, **overrides):
        tx = fn.build_transaction({
            "from": self.address,
            "nonce": self.w3.eth.get_transaction_count(self.address),
            "chainId": self.chain_id,
            "gas": 300_000,
            "gasPrice": self.w3.eth.gas_price,
            "value": 0,
            **overrides,
        })
        try:
            tx["gas"] = self.w3.eth.estimate_gas({k: v for k, v in tx.items() if k != "gas"})
        except Exception:
            pass
        signed = self.account.sign_transaction(tx)
        h = self.w3.eth.send_raw_transaction(signed.raw_transaction)
        return self.w3.eth.wait_for_transaction_receipt(h, timeout=120)

    # ---------- vault: deposit / withdraw / claim yield ----------

    def deposit(self, usdc: float) -> bytes:
        """Deposit USDC into the collateral vault. Earning Aave APY from this block."""
        amount = self.to_usdc(usdc)
        # 1. approve vault to pull USDC
        tx = self._send(self._usdc.functions.approve(self.vault_address, amount))
        # 2. deposit
        r = self._send(self.vault.functions.deposit(amount))
        return r.transactionHash

    def create_and_fund(self, payee: str, amount_usdc: float, task_hash: bytes, deadline_hours: int = 24) -> bytes:
        """Create an escrow and fund it in one tx. Returns the escrow id (bytes32)."""
        if not self.escrow:
            raise RuntimeError("no escrow address configured")
        amount = self.to_usdc(amount_usdc)
        # 1. approve escrow to pull USDC
        self._send(self._usdc.functions.approve(self.escrow_address, amount))
        # 2. createAndFund
        deadline = int(time.time()) + deadline_hours * 3600
        r = self._send(self.escrow.functions.createAndFund(
            Web3.to_checksum_address(payee) if hasattr(Web3, "to_checksum_address") else payee,
            Web3.to_checksum_address(self.usdc()) if hasattr(Web3, "to_checksum_address") else self.usdc(),
            amount, task_hash, deadline,
        ))
        # web3.py event processing
        try:
            events = self.escrow.events.EscrowCreated().process_receipt(r)
            if events:
                return events[0]["args"]["id"]
        except Exception:
            pass
        # fallback: find the log whose address matches the escrow contract
        for log in r.logs:
            if log["address"].lower() == self.escrow_address.lower():
                return log["topics"][1]
        raise RuntimeError("could not find EscrowCreated event in receipt")

    def release(self, escrow_id) -> bytes:
        """Release escrow to payee. Fee is deducted automatically."""
        if not self.escrow:
            raise RuntimeError("no escrow address configured")
        eid = escrow_id if isinstance(escrow_id, bytes) else bytes.fromhex(escrow_id.replace("0x", ""))
        r = self._send(self.escrow.functions.release(eid))
        return r.transactionHash

    def refund(self, escrow_id) -> bytes:
        """Refund the payer. Only callable after deadline."""
        if not self.escrow:
            raise RuntimeError("no escrow address configured")
        eid = escrow_id if isinstance(escrow_id, bytes) else bytes.fromhex(escrow_id.replace("0x", ""))
        r = self._send(self.escrow.functions.refund(eid))
        return r.transactionHash

    def withdraw(self, usdc: float) -> bytes:
        """Withdraw USDC from the vault. Burns your share of aTokens."""
        amount = self.to_usdc(usdc)
        r = self._send(self.vault.functions.withdraw(amount))
        return r.transactionHash

    def balance(self) -> float:
        """Your current USDC value in the vault (principal + accrued yield)."""
        if not self.vault:
            raise RuntimeError("no vault address configured")
        raw = self.vault.functions.aTokenBalanceOf(self.address).call()
        return self.from_usdc(raw)

    def claim_yield(self) -> bytes:
        """Anyone can call skimYield; 30% goes to yieldRecipient, 70% stays for depositors."""
        if not self.vault:
            raise RuntimeError("no vault address configured")
        r = self._send(self.vault.functions.skimYield())
        return r.transactionHash

    def locked_stake(self) -> float:
        if not self.vault:
            return 0.0
        pos = self.vault.functions.positions(self.address).call()
        return self.from_usdc(pos[1])

    def apy_estimate(self) -> float:
        """Aave v3 USDC supply APY on Base, fetched from Aave's public rate API."""
        try:
            from urllib.request import urlopen
            import json as _json
            with urlopen("https://aave-api-v2.aave.com/data/rates-history", timeout=10) as r:
                data = _json.loads(r.read())
            for reserve in data:
                if reserve.get("reserve", {}).get("symbol") == "USDC" and reserve.get("reserve", {}).get("network", "").lower() == "base":
                    return float(reserve.get("currentLiquidityRate", 0)) / 1e25
        except Exception:
            pass
        return 0.04  # 4% fallback

    # ---------- task board (HTTP) ----------

    def _http(self, method: str, path: str, body: Optional[dict] = None) -> dict:
        url = f"{self.api_url}{path}"
        data = json.dumps(body).encode() if body is not None else None
        req = urllib.request.Request(url, data=data, method=method)
        req.add_header("Content-Type", "application/json")
        if self.api_key:
            req.add_header("Authorization", f"Bearer {self.api_key}")
        with urllib.request.urlopen(req, timeout=15) as r:
            return json.loads(r.read())

    def browse_tasks(self, source: Optional[str] = None, category: Optional[str] = None) -> list[Task]:
        """Browse scraped + posted tasks. Default: open tasks only."""
        qs = "status=open"
        if source: qs += f"&source={source}"
        if category: qs += f"&category={category}"
        out = self._http("GET", f"/tasks?{qs}")
        return [Task.from_dict(t) for t in out.get("tasks", [])]

    def get_task(self, task_id: str) -> Task:
        return Task.from_dict(self._http("GET", f"/tasks/{task_id}"))

    def post_task(
        self,
        title: str,
        description: str,
        budget_usdc: float,
        category: str = "general",
        deadline_hours: int = 24,
        required_stake: float = 0.0,
    ) -> Task:
        if not self.address:
            raise RuntimeError("post_task requires a wallet (private_key)")
        body = {
            "title": title, "description": description,
            "budget_usdc": budget_usdc, "category": category,
            "deadline_hours": deadline_hours,
            "required_stake": required_stake,
            "buyer_address": self.address,
        }
        return Task.from_dict(self._http("POST", "/tasks", body))

    def claim(self, task_id: str) -> Task:
        if not self.address:
            raise RuntimeError("claim requires a wallet")
        return Task.from_dict(self._http("POST", f"/tasks/{task_id}/claim",
                                        {"seller_address": self.address}))

    def submit(self, task_id: str, proof: str) -> Task:
        """Submit your work for review. Buyer then releases or slashes."""
        if not self.address:
            raise RuntimeError("submit requires a wallet")
        return Task.from_dict(self._http("POST", f"/tasks/{task_id}/submit",
                                        {"seller_address": self.address, "proof": proof}))

    def slash(self, task_id: str) -> Task:
        """Buyer calls this on a failed / timed-out task. Sends the agent's stake to the buyer."""
        if not self.address:
            raise RuntimeError("slash requires a wallet")
        return Task.from_dict(self._http("POST", f"/tasks/{task_id}/slash",
                                        {"caller": self.address}))

    def settle_task(self, task_id: str, escrow_id, tx_hash: str) -> Task:
        return Task.from_dict(self._http("POST", f"/tasks/{task_id}/settle",
                                        {"escrow_id": escrow_id.hex() if isinstance(escrow_id, bytes) else escrow_id,
                                         "tx_hash": tx_hash}))

    def report_event(self, kind: str, escrow_id, tx_hash: str, **kw) -> dict:
        body = {
            "kind": kind,
            "escrow_id": escrow_id.hex() if isinstance(escrow_id, bytes) else escrow_id,
            "tx_hash": tx_hash,
            "chain_id": self.chain_id,
            **kw,
        }
        return self._http("POST", "/events", body)

    def stats(self) -> dict:
        return self._http("GET", "/stats")
