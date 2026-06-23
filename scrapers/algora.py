"""Algora.io scraper.

Algora is a Phoenix LiveView site (no public JSON API for bounties).
It serves challenge boards at:
    https://algora.io/challenges                 (challenge index)
    https://algora.io/challenges/<slug>          (a challenge with bountied issues)

Each challenge page lists a top-line pool amount (e.g. "$15,000 Land a
fantastic 🦀") and a list of GitHub issues. The pool amount is the
total bounty for the challenge, split across the issues. We treat
each issue as its own task with a per-issue budget of (pool / N).
"""
from .base import Scraper, ScrapedTask
from typing import Iterator
import re
import time
import urllib.request
from http.client import IncompleteRead
from urllib.error import URLError


def _fetch_html(url: str, timeout: int = 30, retries: int = 3) -> str:
    last_err: Exception | None = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AgentPay/0.2",
                "Accept": "text/html,application/xhtml+xml",
                "Accept-Encoding": "identity",
            })
            with urllib.request.urlopen(req, timeout=timeout) as r:
                data = r.read()
                # decompress if gzipped
                if r.headers.get("Content-Encoding") == "gzip":
                    import gzip
                    data = gzip.decompress(data)
                return data.decode("utf-8", errors="ignore")
        except (URLError, IncompleteRead, TimeoutError, ConnectionError) as e:
            last_err = e
            time.sleep(0.5 + attempt * 0.5)
    raise last_err if last_err else RuntimeError("fetch failed")


def _parse_first_dollar(text: str) -> int | None:
    """Return the first plausible dollar amount >= $50 in `text`."""
    for m in re.finditer(r"\$\s*([0-9][0-9,]{1,9})", text):
        try:
            v = int(m.group(1).replace(",", ""))
            if v >= 50:
                return v
        except Exception:
            continue
    return None


def _list_challenge_slugs() -> list[str]:
    try:
        html = _fetch_html("https://algora.io/challenges")
    except Exception as e:
        print(f"[algora] /challenges fetch failed: {e}")
        return []
    return sorted(set(re.findall(r'href="/challenges/([a-zA-Z0-9_-]+)"', html)))


def _scrape_challenge_page(slug: str) -> list[ScrapedTask]:
    """Scrape one /challenges/<slug> page. Returns bountied issues with amounts."""
    try:
        html = _fetch_html(f"https://algora.io/challenges/{slug}")
    except Exception as e:
        print(f"[algora] challenge {slug} fetch failed: {e}")
        return []

    # Pool amount: the first $X in the page header (before the issue list).
    # Heuristic: the pool is in the first 8KB of the page (Algora header is at the top).
    header = html[:8192]
    pool = _parse_first_dollar(header) or 0
    if not pool:
        pool = _parse_first_dollar(html) or 0

    # All GitHub issues linked on the page
    issue_links = list(set(re.findall(
        r'href="(https://github\.com/([^/]+)/([^/]+)/issues/(\d+))"',
        html,
    )))
    if not issue_links:
        return []

    # Per-issue budget = pool / N (integer round), with min $50 floor
    per_issue = max(50, round(pool / max(1, len(issue_links))))

    tasks: list[ScrapedTask] = []
    for full_url, org, repo, n in issue_links:
        tasks.append(ScrapedTask(
            source="algora",
            external_id=f"{org}/{repo}#{n}",
            title=f"Algora: {org}/{repo}#{n} (~${per_issue})",
            description=(
                f"Algora challenge: {slug}. Pool ${pool} across "
                f"{len(issue_links)} issue(s) (per-issue budget ${per_issue}). "
                f"See {full_url}"
            ),
            category="code",
            budget_usdc=float(per_issue),
            buyer_address=org,
            url=full_url,
            deadline_hours=336,
            required_stake=round(min(per_issue * 0.20, 50.0), 2),
        ))
    return tasks


class AlgoraScraper(Scraper):
    name = "algora"

    def __init__(self, min_usd: float = 50.0):
        self.min_usd = min_usd

    def fetch(self) -> Iterator[ScrapedTask]:
        slugs = _list_challenge_slugs()
        if not slugs:
            print("[algora] no challenges found; site structure may have changed")
            return
        for slug in slugs:
            for t in _scrape_challenge_page(slug):
                if t.budget_usdc >= self.min_usd:
                    yield t
