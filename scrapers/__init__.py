"""Scrapers: pull paid tasks from the open web into AgentPay's task pool.

Each scraper implements:
    class Scraper:
        name: str
        def fetch() -> Iterable[ScrapedTask]: ...

A ScrapedTask is normalized so the API can serve it via /tasks.
"""
from .base import Scraper, ScrapedTask
from .runx import RunxScraper
from .algora import AlgoraScraper
from .github import GitHubBountyScraper
from .polar import PolarScraper
from .reddit import RedditScraper
from .fiverr import FiverrScraper

SCRAPERS = {
    "runx":          RunxScraper,
    "algora":        AlgoraScraper,
    "github-bounty": GitHubBountyScraper,
    "polar":         PolarScraper,            # currently disabled (api private)
    "reddit":        RedditScraper,           # currently disabled (ip-blocked)
    "fiverr":        FiverrScraper,           # disabled (commercial)
}

# Default-enable only the ones that actually return tasks right now.
DEFAULT_ENABLED = ("runx", "algora", "github-bounty")

__all__ = ["Scraper", "ScrapedTask", "SCRAPERS", "DEFAULT_ENABLED"]
