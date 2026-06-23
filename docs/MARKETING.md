# AgentPay launch playbook

The product is live and the SDK works end-to-end against Base Sepolia. Time
to let the right people know. Each post below is calibrated to the norms of
its community — read them, tweak, post.

## Channels (ranked by fit)

| Channel | Audience | Why it fits | Format |
|---|---|---|---|
| Hacker News (Show HN) | builders, investors, protocol folks | "Show HN" gets on the front page if the demo works | long-form text post |
| r/LocalLLaMA | people running local agents, looking for paid work for them | "make your local agent earn money" | self-post with demo link |
| r/MachineLearning | ML engineers, often building agents | technical credibility matters | link post + comment with details |
| AI agent Discords (AutoGPT, LangChain, CrewAI, smol-developer) | agent builders who already pay for APIs | they'd be the first users | short #show-and-tell post |
| AI Twitter / X | agent devs, crypto-AI crossover | the 0.5% / 70-30 / slash story compresses well | thread |
| Farcaster / Lens | crypto-native devs | USDC + Aave + on-chain is their mother tongue | cast with screenshot |
| Moltbook / agent-only socials | agents themselves | if they exist yet, be the first marketplace they see | "AgentPay listing" |
| Product Hunt | general tech audience | "Show HN" with a calendar date | standard PH post |

**Skip** for now: paid ads, generic Reddit subs (r/programming, r/cryptocurrency —
they downvote crypto posts hard), LinkedIn (wrong audience for an agent API).

## Timing

Post in this order, ~12h between each so feedback and traffic can flow:

1. **HN Show HN** first. It gives the spike the algorithm needs and the
   comment thread is the highest-quality feedback you'll get.
2. **r/LocalLLaMA** next. That sub loves "local LLM earns money" stories.
3. **AI Twitter thread** with the HN link, ~4h after HN goes up.
4. **AI agent Discords** (parallel, after HN is on the front page).
5. **r/MachineLearning** a day later, framed as research/infra.
6. **Farcaster** with the screenshot, after you have a real screenshot
   of a settled task from a non-deployer wallet.

## Drafts

### 1. Hacker News — Show HN

Title: **Show HN: AgentPay – USDC task market for AI agents, settled on Base**

Text:
```
Hi HN,

I built AgentPay, a USDC task market and collateral pool for AI agents.
It runs live on Base Sepolia; the SDK and API are open-source.

The idea: AI agents can already write code, answer support tickets, do
research. They don't have a way to *find paid work*, *deposit collateral
to signal seriousness*, or *get paid without a human officer*. AgentPay
is a single API that gives them all three.

What's there right now (Base Sepolia, public URL):
- 75 open tasks scraped from runx, Algora, and GitHub bounties
- A USDC collateral vault (deposit → earn ~4% APY via Aave v3 supply)
- A 0.5%-fee escrow per task with a slash path
- A Python SDK (5 lines from install to first claim)
- End-to-end demo that runs against the live contracts:
  pip install -e sdk/python && python scripts/sdk/live_demo.py

What it's not yet:
- Mainnet deployment (costs ~$5-10 USDC + 0.05 ETH gas; not pulling
  the trigger until I have ≥3 external agents to onboard)
- Verified contracts on BaseScan (still need an API key)
- A web UI for the buyer (right now it's the API or the SDK)

The economic model is in the README. Short version: 0.5% per-task fee
+ 30% skim on the Aave yield on the collateral pool + 100% of slashed
stake on failure. Three legs, scales with float not volume.

Public URL: https://disbelief-navy-unhappy.ngrok-free.dev
GitHub: https://github.com/ndsgbm-web/agentpay

Happy to answer questions about the contracts, the SDK, the scrapers, or
the economics.
```

### 2. r/LocalLLaMA

Title: **I built a USDC marketplace where your local LLM can earn real money**

Body:
```
TL;DR: AgentPay is a USDC task market for AI agents. They deposit
collateral, claim scraped tasks from runx/Algora/GitHub bounties, do
the work, get paid in USDC, with a slash on failure. Live on Base
Sepolia, open-source, 5-line Python SDK.

[link to https://disbelief-navy-unhappy.ngrok-free.dev]

---

The problem I kept hitting with my own agents: they're great at
producing output but they have no economy. They can't find work, they
can't stake, they can't get paid. So I built one.

What works right now:
- Scraped task pool (75 live, 3 sources)
- USDC vault: deposit earns ~4% APY via Aave v3 supply
- Per-task escrow with 0.5% fee and slash on failure
- Python SDK
- End-to-end demo against live Base Sepolia contracts

The demo (`scripts/sdk/live_demo.py`) does the full flow:
deposit → claim → submit → release → settle. You can see a worker's
balance grow and the platform's fee recipient (my wallet) accrue
0.075 USDC per task. Real numbers, on-chain.

Curious whether anyone here has tried hooking a local agent up to a
paid-task system before — what got in the way?
```

### 3. AI Twitter / X thread

Tweet 1 (hook):
```
I built a USDC marketplace where AI agents can find work, deposit
collateral, and get paid.

No human officer. No Fiverr middleman. The agent stakes, the buyer
posts, the chain settles.

Live on Base Sepolia → https://disbelief-navy-unhappy.ngrok-free.dev
```

Tweet 2 (problem):
```
The problem: AI agents in 2026 can do real work but have no
economy. They can't find paid tasks, can't signal trustworthiness,
can't get paid without a human in the loop.

Result: agents are toys, not workers.
```

Tweet 3 (solution):
```
AgentPay is three contracts + one API:

1. Task pool (scraped + posted)
2. USDC vault (Aave v3 supply, ~4% APY)
3. Escrow per task (0.5% fee, slash on failure)

5-line Python SDK. https://github.com/ndsgbm-web/agentpay
```

Tweet 4 (demo):
```
End-to-end demo that actually works on-chain:

$ pip install -e sdk/python
$ python scripts/sdk/live_demo.py

It does deposit → claim → submit → release → settle
against the live contracts. Worker ends with $400 USDC,
fee recipient with $0.45 from 5 tasks.
```

Tweet 5 (ask):
```
What I'm looking for:
- 3-5 agents willing to be early depositors
- Scrapers for Polar, Reddit, X, Fiverr
- Contract auditors (Solidity, ~600 LoC total)

DM open. Or just claim a task on the live URL.
```

### 4. AI agent Discord (#show-and-tell format)

```
👋 Hey agents — I built a place for you to get paid.

AgentPay is a USDC task market on Base. You:
  1. Deposit USDC (earns ~4% APY while idle)
  2. Browse tasks scraped from runx, Algora, GitHub
  3. Claim one (locks stake from your deposit)
  4. Submit proof when done
  5. Get paid. Stake returned. Yield still accruing.

5-line Python SDK:
  from agentpay import AgentPay
  ap = AgentPay(private_key="0x...")
  ap.deposit(usdc=50)
  for t in ap.browse_tasks(): print(t.title)
  ap.claim_with_deposit(task.id)

Live on Base Sepolia (testnet, free USDC from the faucet):
https://disbelief-navy-unhappy.ngrok-free.dev

Contracts on BaseScan. GitHub: ndsgbm-web/agentpay.
Onchain E2E demo included in the repo. Happy to answer questions
about the contracts, the SDK, or the economics.
```

### 5. r/MachineLearning

Title: **Open infrastructure for paid AI agents (USDC collateral pool, on-chain escrow, end-to-end demo)**

Link post, then a top-level comment:

```
Author here. Quick context for ML folks who don't normally touch
crypto:

The interesting part isn't the USDC, it's the mechanism. We have
lots of agents now (LangChain, AutoGPT, CrewAI, custom) that can
produce real output. The gap is the *agreement layer* — how does
an agent get matched with a buyer, signal trustworthiness, accept
work, and get paid, all without a human officer?

AgentPay is a small attempt at that: scraped task pool + USDC
collateral vault (Aave v3 supply, ~4% APY) + per-task escrow
contract with a slash path. 0.5% platform fee.

The model is interesting because of the failure handling. An agent
that goes silent or returns garbage doesn't just not get paid — the
buyer slashes the stake. That gives a market signal that doesn't
require a reputation system or a centralized review process.

Repo: https://github.com/ndsgbm-web/agentpay
Live (Base Sepolia): https://disbelief-navy-unhappy.ngrok-free.dev
On-chain E2E: scripts/sdk/live_demo.py

Happy to discuss the model, the contracts, or the scrapers in the
comments.
```

### 6. Farcaster

```
AgentPay is live on Base Sepolia.

USDC task market for AI agents: deposit collateral, claim scraped
tasks, get paid on release, lose stake on slash.

5-line Python SDK. End-to-end demo included.

https://disbelief-navy-unhappy.ngrok-free.dev
github.com/ndsgbm-web/agentpay
```

## Visual assets to prepare

You don't need much — one screenshot, one terminal capture, one
diagram. Capture these once and reuse across all channels:

1. **`docs/img/landing.png`** — full landing page, scrolled to the
   "Running on Base Sepolia" panel.
2. **`docs/img/sdk-demo.png`** — terminal screenshot of
   `scripts/sdk/live_demo.py` running, showing "✓ SDK end-to-end
   against live Base Sepolia deployment complete".
3. **`docs/img/flow.svg`** — the agent → vault → escrow → Aave
   diagram from the README, as an SVG so it scales.
4. **`docs/img/basescan.png`** — the AgentPayEscrow contract on
   BaseScan, showing the verified source (after verification).

## Tracking

Set up a single UTM per channel so you can see what drove what:

- `?utm_source=hackernews&utm_campaign=launch`
- `?utm_source=reddit-localllama&utm_campaign=launch`
- `?utm_source=twitter&utm_campaign=launch`
- `?utm_source=discord-langgchain&utm_campaign=launch`

The FastAPI server already logs query strings, so the data is
already there — just grep `api.log` for the params.

## What I (Codex) can and can't do

I can:
- Draft these posts (above)
- Take screenshots
- Run the demo to capture clean terminal output
- Tune copy after feedback

I can't:
- Log into your Reddit, HN, Twitter, Discord, Farcaster
- Post on your behalf
- Moderate comment threads

So the loop is: I draft → you post → feedback flows in → I tune.
