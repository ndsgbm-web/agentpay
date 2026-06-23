"""Reddit scraper.

Uses Reddit's public JSON endpoints (no auth needed for public subreddits):
    https://www.reddit.com/r/<sub>/new.json
We scrape r/forhire and r/slavelabour for task posts.
"""
from .base import Scraper, ScrapedTask, http_get_json
from typing import Iterator


class RedditScraper(Scraper):
    name = "reddit"
    DEFAULT_SUBS = ("forhire", "slavelabour", "bounties")
    BUDGET_HINTS = ("$", "usd", "pay", "budget", "报酬", "工资", "费用")

    def __init__(self, subs=DEFAULT_SUBS, limit: int = 25):
        self.subs = subs
        self.limit = limit

    def fetch(self) -> Iterator[ScrapedTask]:
        for sub in self.subs:
            try:
                url = f"https://www.reddit.com/r/{sub}/new.json?limit={self.limit}"
                data = http_get_json(url)
            except Exception as e:
                print(f"[reddit] r/{sub} fetch failed: {e}")
                continue
            for child in data.get("data", {}).get("children", []):
                d = child.get("data", {})
                title = d.get("title", "")
                selftext = d.get("selftext", "")
                full = f"{title}\n{selftext}".lower()
                if not any(h in full for h in self.BUDGET_HINTS):
                    continue
                # crude budget extraction: look for $N or $NN
                import re
                m = re.search(r"\$\s*(\d+(?:\.\d+)?)", selftext + " " + title)
                budget = float(m.group(1)) if m else 0.0
                if budget <= 0:
                    continue
                yield ScrapedTask(
                    source="reddit",
                    external_id=d.get("id", ""),
                    title=title[:200],
                    description=selftext[:2000],
                    category="general",
                    budget_usdc=budget,
                    url=f"https://reddit.com{d.get('permalink','')}",
                    buyer_address="",  # reddit users don't expose wallet
                    deadline_hours=72,
                    raw={"sub": sub, "author": d.get("author", "")},
                )
