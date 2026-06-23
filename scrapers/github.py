"""GitHub issues with bounty labels scraper.

Uses GitHub's public REST API to find open issues labeled with common
"bounty" markers. No auth required for low-volume reads (we get 60/h
anonymous, so we cap per call).

Useful queries:
  - label:"bounty"   is:open   archived:false
  - label:"💰bounty" is:open
  - label:"🤑 bounty" is:open
  - "bounty" in:title is:open
"""
from .base import Scraper, ScrapedTask, http_get_json
from typing import Iterator


# Queries to find bounty-tagged issues. Each one is tried; the dedup
# is by (org, repo, issue#).
QUERIES = [
    'label:"💰bounty" is:open archived:false',
    'label:"🤑 bounty" is:open archived:false',
    'label:"bounty" is:open archived:false',
    '"bounty" in:title is:open archived:false',
    '"reward" in:title is:open label:enhancement archived:false',
]


def _amounts_from_text(text: str) -> list[int]:
    """Extract plausible dollar amounts from issue title/body."""
    import re
    out: list[int] = []
    for m in re.finditer(r"\$\s*([0-9][0-9,]{1,9})", text or ""):
        try:
            v = int(m.group(1).replace(",", ""))
            if 25 <= v <= 1_000_000:
                out.append(v)
        except Exception:
            continue
    return out


class GitHubBountyScraper(Scraper):
    name = "github-bounty"
    DEFAULT_API = "https://api.github.com"

    def __init__(self, api_url: str = DEFAULT_API, per_query: int = 30, min_usd: float = 25.0):
        self.api_url = api_url.rstrip("/")
        self.per_query = per_query
        self.min_usd = min_usd

    def _search(self, q: str) -> Iterator[ScrapedTask]:
        import urllib.parse
        url = f"{self.api_url}/search/issues?per_page={self.per_query}&sort=updated&order=desc&q={urllib.parse.quote(q)}"
        try:
            data = http_get_json(url, headers={"Accept": "application/vnd.github+json"})
        except Exception as e:
            print(f"[github] search failed for {q!r}: {e}")
            return
        for it in data.get("items", []):
            repo_url = it.get("repository_url", "")                # .../repos/<org>/<repo>
            repo_parts = repo_url.rsplit("/", 2)[-2:]              # [org, repo]
            if len(repo_parts) != 2:
                continue
            org, repo = repo_parts
            n = it.get("number", "")
            ext_id = f"{org}/{repo}#{n}"
            title = it.get("title", "Untitled")
            body = it.get("body") or ""
            amounts = _amounts_from_text(title + " " + body)
            if not amounts:
                # skip issues that don't quote a dollar bounty
                continue
            budget = max(amounts)
            if budget < self.min_usd:
                continue
            html_url = it.get("html_url", "")
            labels = [l.get("name", "") for l in it.get("labels", [])]
            yield ScrapedTask(
                source="github-bounty",
                external_id=ext_id,
                title=(title[:120] if not title.startswith("[") else title[:120]),
                description=f"{body[:600]}\n\nLabels: {', '.join(labels)}",
                category="code",
                budget_usdc=float(budget),
                buyer_address=org,
                url=html_url,
                deadline_hours=720,                                 # 30 days
                required_stake=round(min(budget * 0.10, 50.0), 2),
            )

    def fetch(self) -> Iterator[ScrapedTask]:
        seen: set[str] = set()
        for q in QUERIES:
            for t in self._search(q):
                if t.external_id in seen:
                    continue
                seen.add(t.external_id)
                yield t
