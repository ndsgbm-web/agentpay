"""Bridge: take a completed runx task and settle it in USDC via AgentPay.

Use case: a runx agent finishes a task → it tells AgentPay → the buyer
sees the proof → USDC is released to the runx agent's wallet.

This is the integration glue. Production agents run the same flow.
"""
from __future__ import annotations

import os
import sys
from typing import Optional

try:
    from agentpay import AgentPay
except ImportError:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "python"))
    from agentpay import AgentPay


def settle_via_agentpay(
    pay: AgentPay,
    runx_task_id: str,
    proof: str,
    timeout_minutes: int = 60,
) -> dict:
    """Submit a completed runx task to AgentPay for USDC settlement.

    Args:
        pay: an AgentPay instance (must have private_key + escrow_address)
        runx_task_id: the AgentPay task id (claimed via pay.claim)
        proof: string/URL describing what you delivered
        timeout_minutes: how long to wait for buyer to release (not implemented)
    Returns:
        dict with status + transaction info
    """
    pay.submit(runx_task_id, proof=proof)
    return {
        "task_id": runx_task_id,
        "status": "submitted",
        "note": "buyer has 24h to release; otherwise anyone can settle",
    }


if __name__ == "__main__":
    # demo: deposit, claim, submit (against the in-memory test EVM)
    # run: PYTHONPATH=sdk/python python sdk/integrations/bridge_runx.py
    print("AgentPay bridge module — import settle_via_agentpay() in your runx handler.")
