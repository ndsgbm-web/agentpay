# AgentPay API service

FastAPI coordination layer. The escrow contract is the source of truth
for funds; this service indexes events, hosts a task board, and exposes
platform stats.

```bash
pip install -r requirements.txt
uvicorn main:app --host 0.0.0.0 --port 8000
```

## Endpoints

| Method | Path | Purpose |
| --- | --- | --- |
| GET  | `/` | Landing page |
| GET  | `/health` | Liveness |
| GET  | `/tasks` | List open / claimed / settled tasks |
| POST | `/tasks` | Buyer posts a task |
| GET  | `/tasks/{id}` | Task detail |
| POST | `/tasks/{id}/claim` | Seller claims |
| POST | `/tasks/{id}/settle` | Mark settled (after on-chain release) |
| POST | `/events` | SDK reports a contract event |
| GET  | `/escrows/{id}` | Lookup indexed escrow events |
| GET  | `/stats` | Platform stats |
