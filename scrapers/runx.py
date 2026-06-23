"""runx marketplace scraper.

runx exposes a public listing API. We pull community-tier skills (no
verified publisher required) since those are most likely to be open
for third-party agents.
"""
from .base import Scraper, ScrapedTask, http_get_json
from typing import Iterator


class RunxScraper(Scraper):
    name = "runx"
    DEFAULT_API = "https://api.runx.ai"

    def __init__(self, api_url: str = DEFAULT_API, tier: str = "community", limit: int = 50):
        self.api_url = api_url.rstrip("/")
        self.tier = tier
        self.limit = limit

    def fetch(self) -> Iterator[ScrapedTask]:
        try:
            data = http_get_json(f"{self.api_url}/v1/skills?tier={self.tier}&limit={self.limit}")
        except Exception as e:
            print(f"[runx] fetch failed: {e}")
            return
        for skill in data.get("skills", []):
            yield ScrapedTask(
                source="runx",
                external_id=skill.get("id", ""),
                title=skill.get("name", "Untitled skill"),
                description=skill.get("description", ""),
                category=skill.get("category", "ops"),
                budget_usdc=0.5,                    # runx skills priced per-run
                buyer_address=skill.get("owner", ""),
                url=skill.get("page_url", f"https://runx.ai/x/{skill.get('id','')}"),
                raw=skill,
            )
