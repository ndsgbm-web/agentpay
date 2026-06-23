"""Fiverr scraper.

Fiverr doesn't have a public API, so we use the public search HTML
endpoint. This is fragile; treat results as leads, not canonical.
"""
from .base import Scraper, ScrapedTask
from typing import Iterator
import re


class FiverrScraper(Scraper):
    name = "fiverr"
    # Note: Fiverr is a buyer-side market. This scraper surfaces
    # buy-requests that AI agents can fulfill (the inverse of Fiverr's
    # normal flow). We pull from Fiverr's BuyerRequests / Briefs feed.
    ENABLED = False  # off by default; enable with API key or proxy

    def fetch(self) -> Iterator[ScrapedTask]:
        # Skeleton: real implementation needs Fiverr API access.
        # Marked disabled to avoid noisy failures.
        return
        yield  # pragma: no cover
