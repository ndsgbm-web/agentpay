#!/usr/bin/env bash
# Start the AgentPay API, scrape every enabled source, then foreground the API.
set -euo pipefail
ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

DATA_DIR="${AGENTPAY_DATA:-$ROOT/.agentpay-data}"
PORT="${AGENTPAY_PORT:-8000}"
mkdir -p "$DATA_DIR"

# 1) start API in background
echo "==> starting API on :$PORT"
env AGENTPAY_DATA="$DATA_DIR" AGENTPAY_PORT="$PORT" \
    python3 -m uvicorn api.main:app --host 0.0.0.0 --port "$PORT" --log-level warning \
    > "$DATA_DIR/api.log" 2>&1 &
API_PID=$!

# 2) wait for it to come up
for i in {1..30}; do
    if curl -s "http://127.0.0.1:$PORT/health" > /dev/null 2>&1; then
        break
    fi
    sleep 0.4
done

# 3) scrape every enabled source and push to the API.
#    Each scraper is run in a subshell so one slow source doesn't block others.
echo "==> scraping sources (runx, algora, github-bounty)"
python3 -c "
import sys, json, requests, traceback
sys.path.insert(0, '.')
from scrapers import DEFAULT_ENABLED
from scrapers.base import Scraper
from scrapers.runx import RunxScraper
from scrapers.algora import AlgoraScraper
from scrapers.github import GitHubBountyScraper

API = 'http://127.0.0.1:${PORT}'

def ingest(t):
    return requests.post(f'{API}/tasks/ingest', json={
        'source': t.source,
        'external_id': t.external_id,
        'title': t.title,
        'description': t.description,
        'category': t.category,
        'budget_usdc': t.budget_usdc,
        'deadline_hours': t.deadline_hours,
        'required_stake': t.required_stake,
        'url': t.url,
        'buyer_address': t.buyer_address,
    }, timeout=5)

def run(name, scraper):
    try:
        tasks = list(scraper.fetch())
    except Exception as e:
        print(f'  {name}: fetch error: {e}')
        return 0, 0
    ok = 0
    for t in tasks:
        try:
            r = ingest(t)
            if r.status_code == 200:
                ok += 1
        except Exception:
            pass
    print(f'  {name}: ingested {ok}/{len(tasks)}')
    return ok, len(tasks)

run('runx',          RunxScraper(limit=50))
run('algora',        AlgoraScraper(min_usd=50))
run('github-bounty', GitHubBountyScraper(per_query=20, min_usd=50))
" 2>&1

# 4) final stats
echo ""
echo "==> stats"
curl -s "http://127.0.0.1:$PORT/stats" | python3 -m json.tool 2>/dev/null || true

# 5) hand off to the foreground API
echo ""
echo "==> API is live on http://127.0.0.1:$PORT  (Ctrl+C to stop)"
wait $API_PID
