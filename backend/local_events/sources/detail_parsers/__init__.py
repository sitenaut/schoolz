"""Per-site detail-page parsers. Each module exposes:

    parse(html: str, url: str, default_categories: list[str], source_name: str) -> RawEvent | None

The SitemapSource selects a parser by its registered name (`parsers[name]`).
"""
from __future__ import annotations

from typing import Callable

from ..base import RawEvent
from . import macaronikid

DetailParser = Callable[[str, str, list[str], str], "RawEvent | None"]

parsers: dict[str, DetailParser] = {
    "macaronikid": macaronikid.parse,
}
