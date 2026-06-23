# agentpay (Python)

USDC escrow for AI agents. See top-level README.

```bash
pip install -e .
```

```python
from agentpay import AgentPay
ap = AgentPay(private_key="0x...", escrow_address="0x...")
eid = ap.create_and_fund(
    payee="0xSELLER", amount_usdc=10,
    task_hash=ap.hash_task("translate-zh-to-en-1000-words"),
    deadline_hours=24,
)
ap.release(eid)
```
