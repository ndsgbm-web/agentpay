"""Polar.sh scraper.

Polar publishes issue bounties as a public JSON feed. We pull the
"open" issues with a non-zero reward.
"""
from .base import Scraper, ScrapedTask, http_get_json
from typing import Iterator


class PolarScraper(Scraper):
    name = "polar"
    DEFAULT_API = "https://api.polar.sh"

    def __init__(self, api_url: str = DEFAULT_API, min_usd: float = 5.0):
        self.api_url = api_url.rstrip("/")
        self.min_usd = min_usd

    def fetch(self) -> Iterator[ScrapedTask]:
        try:
            data = http_get_json(f"{self.api_url}/v1/issues/bounties?limit=50")
        except Exception as e:
            print(f"[polar] fetch failed: {e}")
            return
        items = data.get("items", data.get("data", []))
        for it in items:
            amt = it.get("reward_amount", 0) or 0
            if amt < self.min_usd:
                continue
            yield ScrapedTask(
                source="polar",
                external_id=str(it.get("id", "")),
                title=it.get("title", "Polar bounty"),
                description=it.get("description", ""),
                category="code",
                budget_usdc=float(amt),
                url=it.get("url", ""),
                raw=it,
            )
