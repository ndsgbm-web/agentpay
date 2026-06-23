"""Base types for scrapers."""
from __future__ import annotations

import time
import urllib.request
from dataclasses import dataclass, asdict, field
from typing import Iterable, Optional, Iterator


@dataclass
class ScrapedTask:
    """Normalized task from any source."""
    source: str                  # "runx" | "algora" | "polar" | "reddit" | "fiverr" | ...
    external_id: str             # source's own ID
    title: str
    description: str
    category: str                # "translation" | "code" | "data" | "writing" | ...
    budget_usdc: float
    buyer_address: str = ""      # may be empty if source doesn't expose
    deadline_hours: int = 168    # default 1 week
    url: str = ""                # link back to source
    raw: dict = field(default_factory=dict)

    def to_task_post(self) -> dict:
        d = asdict(self)
        d.pop("raw")
        d.pop("source")
        d["external_id"] = self.external_id
        return d


class Scraper:
    """Base class. Subclass and implement fetch()."""
    name: str = "base"
    enabled: bool = True

    def fetch(self) -> Iterator[ScrapedTask]:
        raise NotImplementedError
        yield  # pragma: no cover

    def __iter__(self) -> Iterator[ScrapedTask]:
        return self.fetch()


def http_get_json(url: str, headers: Optional[dict] = None, timeout: int = 20) -> dict:
    req = urllib.request.Request(url, headers={"User-Agent": "agentpay:scraper:v0.2 (by /u/agentpay_dev)", **(headers or {})})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        import json
        return json.loads(r.read())
