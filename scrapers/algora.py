"""Algora.io scraper.

Algora exposes public bounty lists per org at:
    https://algora.io/api/bounties
We grab the open ones with USDC or stablecoin-equivalent bounties.
"""
from .base import Scraper, ScrapedTask, http_get_json
from typing import Iterator


class AlgoraScraper(Scraper):
    name = "algora"
    DEFAULT_API = "https://algora.io/api"

    def __init__(self, api_url: str = DEFAULT_API, min_usd: float = 5.0):
        self.api_url = api_url.rstrip("/")
        self.min_usd = min_usd

    def fetch(self) -> Iterator[ScrapedTask]:
        try:
            data = http_get_json(f"{self.api_url}/bounties?status=open&limit=50")
        except Exception as e:
            print(f"[algora] fetch failed: {e}")
            return
        for b in data.get("bounties", []):
            amt = b.get("amount_usd", 0) or 0
            if amt < self.min_usd:
                continue
            yield ScrapedTask(
                source="algora",
                external_id=str(b.get("id", "")),
                title=b.get("title", "Algora bounty"),
                description=b.get("description", ""),
                category="code",
                budget_usdc=float(amt),
                buyer_address=b.get("org", {}).get("wallet", ""),
                url=b.get("url", f"https://algora.io/bounty/{b.get('id','')}"),
                raw=b,
            )
