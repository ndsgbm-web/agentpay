"""runx marketplace scraper.

runx exposes a public listing API at /v1/skills. We pull community-tier
skills (no verified publisher required) since those are most likely to
be open for third-party agents.

The API returns `skill_id` (e.g. "kidskills/prospect-sequence") as the
real unique ID, plus `owner`, `page_url`, `install_count`, etc.
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
            # runx returns the real ID as `skill_id` (e.g. "kidskills/prospect-sequence").
            # The legacy `id` field is often empty in practice.
            ext_id = skill.get("skill_id") or skill.get("id") or skill.get("name", "")
            owner = skill.get("owner") or skill.get("owner_handle", "")
            page_url = skill.get("page_url") or (
                f"https://runx.ai/x/{ext_id}" if ext_id else "https://runx.ai"
            )
            # community-tier skills priced per-run; default $0.50, scales lightly w/ installs
            install_count = int(skill.get("install_count", 0) or 0)
            budget = round(max(0.50, min(5.0, 0.50 + install_count * 0.25)), 2)
            yield ScrapedTask(
                source="runx",
                external_id=ext_id,
                title=skill.get("name", "Untitled skill"),
                description=skill.get("description", ""),
                category=skill.get("category", "ops"),
                budget_usdc=budget,
                buyer_address=owner,
                url=page_url,
                raw=skill,
                required_stake=1.0,                 # community: 1 USDC deposit to claim
            )
