"""Sitemap-driven source.

For sites whose listing/calendar pages are JS-rendered shells but whose
per-event detail pages are server-rendered. Walks `sitemap.xml`, filters URLs
by a regex, and scrapes each matching detail page through the scraper service.

Per-page parsing is delegated to a named entry in
`events.sources.detail_parsers.parsers` so each site can have its own selectors
without bloating this module.
"""
from __future__ import annotations

import asyncio
import logging
import re
import xml.etree.ElementTree as ET

import httpx

from .base import RawEvent, Source
from .detail_parsers import parsers as DETAIL_PARSERS
from .scraper import fetch_rendered_html

logger = logging.getLogger(__name__)

DEFAULT_CONCURRENCY = 4
DEFAULT_MAX_PAGES = 80
SITEMAP_TIMEOUT = 30.0


async def _fetch_sitemap_urls(sitemap_url: str, timeout: float = SITEMAP_TIMEOUT) -> list[str]:
    """Return the flat list of <loc> URLs in a sitemap or sitemap-index.

    If the sitemap is an index pointing at other sitemaps, fetch each child
    (capped at 10) and concatenate. Doesn't go deeper than one level — that's
    enough for the targets we care about.
    """
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(sitemap_url, headers={"User-Agent": "schoolz-local-events/1.0"})
        resp.raise_for_status()
        body = resp.content
    try:
        root = ET.fromstring(body)
    except ET.ParseError as exc:
        logger.warning("sitemap_parse_failed", extra={"url": sitemap_url, "error": str(exc)})
        return []

    # Strip namespaces to keep selectors simple.
    def _local(tag: str) -> str:
        return tag.rsplit("}", 1)[-1]

    locs: list[str] = []
    children: list[str] = []
    for child in root.iter():
        if _local(child.tag) == "loc" and child.text:
            text = child.text.strip()
            parent_local = _local(child.getparent().tag) if hasattr(child, "getparent") else None
            # ElementTree doesn't expose parent; classify by sibling structure instead.
            locs.append(text)

    # If <sitemapindex> root, treat all locs as child sitemap URLs.
    if _local(root.tag) == "sitemapindex":
        children = locs[:10]
        locs = []

    if children:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            for child_url in children:
                try:
                    cr = await client.get(child_url, headers={"User-Agent": "schoolz-local-events/1.0"})
                    cr.raise_for_status()
                    croot = ET.fromstring(cr.content)
                    for el in croot.iter():
                        if _local(el.tag) == "loc" and el.text:
                            locs.append(el.text.strip())
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "sitemap_child_failed",
                        extra={"sitemap_url": sitemap_url, "child": child_url, "error": str(exc)},
                    )
                    continue

    return locs


class SitemapSource(Source):
    def __init__(
        self,
        name: str,
        sitemap_url: str,
        url_pattern: str,
        parser_name: str,
        default_categories: list[str] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        concurrency: int = DEFAULT_CONCURRENCY,
        render_wait_selector: str | None = None,
        render_extra_wait_ms: int | None = None,
    ):
        self.name = name
        self.sitemap_url = sitemap_url
        self.url_pattern = re.compile(url_pattern)
        self.parser_name = parser_name
        self.default_categories = default_categories or []
        self.max_pages = min(max(1, int(max_pages)), 500)
        self.concurrency = max(1, min(int(concurrency), 16))
        self.render_wait_selector = render_wait_selector
        self.render_extra_wait_ms = render_extra_wait_ms

        if parser_name not in DETAIL_PARSERS:
            raise ValueError(
                f"unknown detail parser {parser_name!r}; "
                f"available: {', '.join(sorted(DETAIL_PARSERS))}"
            )
        self._parser = DETAIL_PARSERS[parser_name]

    async def _scrape_one(self, url: str, sem: asyncio.Semaphore) -> RawEvent | None:
        async with sem:
            try:
                html, fetched_url = await fetch_rendered_html(
                    url,
                    wait_for_selector=self.render_wait_selector,
                    extra_wait_ms=self.render_extra_wait_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sitemap_detail_fetch_failed",
                    extra={"source": self.name, "url": url, "error": str(exc)},
                )
                return None
            try:
                return self._parser(html, fetched_url, self.default_categories, self.name)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "sitemap_detail_parse_failed",
                    extra={"source": self.name, "url": url, "error": str(exc)},
                )
                return None

    async def list_urls(self) -> list[str]:
        all_locs = await _fetch_sitemap_urls(self.sitemap_url)
        matched = [u for u in all_locs if self.url_pattern.search(u)]
        # De-duplicate while preserving order.
        seen: set[str] = set()
        unique: list[str] = []
        for u in matched:
            if u not in seen:
                seen.add(u)
                unique.append(u)
        return unique[: self.max_pages]

    async def fetch(self) -> list[RawEvent]:
        urls = await self.list_urls()
        if not urls:
            return []
        sem = asyncio.Semaphore(self.concurrency)
        results = await asyncio.gather(*(self._scrape_one(u, sem) for u in urls))
        return [r for r in results if r is not None]

    async def diagnose(self) -> dict[str, str]:
        """Probe info for verbose test-fetch mode.

        Lists how many sitemap URLs matched, then attempts to parse just the
        first match (1 scraper call) so admins can see whether the parser
        produces a sensible event without scraping everything.
        """
        try:
            urls = await self.list_urls()
        except Exception as exc:  # noqa: BLE001
            return {"_error": f"sitemap fetch failed: {type(exc).__name__}: {exc}"}
        if not urls:
            return {
                "matched_urls": "0",
                "_note": f"no sitemap URLs matched pattern {self.url_pattern.pattern!r}",
            }

        first = urls[0]
        try:
            html, fetched_url = await fetch_rendered_html(
                first,
                wait_for_selector=self.render_wait_selector,
                extra_wait_ms=self.render_extra_wait_ms,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "matched_urls": str(len(urls)),
                "first_url": first,
                "_error": f"fetch failed: {type(exc).__name__}: {exc}",
            }
        try:
            raw = self._parser(html, fetched_url, self.default_categories, self.name)
        except Exception as exc:  # noqa: BLE001
            return {
                "matched_urls": str(len(urls)),
                "first_url": first,
                "html_chars": str(len(html)),
                "_error": f"parser failed: {type(exc).__name__}: {exc}",
            }
        return {
            "matched_urls": str(len(urls)),
            "max_pages_cap": str(self.max_pages),
            "concurrency": str(self.concurrency),
            "first_url": first,
            "first_html_chars": str(len(html)),
            "first_parsed_title": (raw.title if raw else "(parser returned None)"),
            "first_parsed_start": (raw.start_time.isoformat() if raw and raw.start_time else "-"),
            "first_parsed_venue": (raw.venue_name or "-") if raw else "-",
        }
