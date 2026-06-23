"""AgentPay — USDC task market + escrow for AI agents.

Layout:
  - AgentPay  : high-level client (vault + escrow + task board)
  - Task      : task dataclass
  - ESCROW_ABI, VAULT_ABI, USDC_ABI: raw ABIs if you want to roll your own
"""
from .client import (
    AgentPay, Task, USDC_ADDRESSES, AAVE_POOL_BASE,
    ESCROW_ABI, VAULT_ABI, USDC_ABI,
)

__version__ = "0.1.0"
__all__ = [
    "AgentPay", "Task",
    "USDC_ADDRESSES", "AAVE_POOL_BASE",
    "ESCROW_ABI", "VAULT_ABI", "USDC_ABI",
]
