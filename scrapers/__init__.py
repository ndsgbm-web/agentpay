"""Scrapers: pull paid tasks from the open web into AgentPay's task pool.

Each scraper implements:
    class Scraper:
        name: str
        def fetch(self) -> Iterable[ScrapedTask]: ...

A ScrapedTask is normalized so the API can serve it via /tasks.
"""
from .base import Scraper, ScrapedTask
from .runx import RunxScraper
from .algora import AlgoraScraper
from .polar import PolarScraper
from .reddit import RedditScraper
from .fiverr import FiverrScraper

SCRAPERS = {
    "runx":   RunxScraper,
    "algora": AlgoraScraper,
    "polar":  PolarScraper,
    "reddit": RedditScraper,
    "fiverr": FiverrScraper,
}

__all__ = ["Scraper", "ScrapedTask", "SCRAPERS"]
