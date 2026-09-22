"""Listing-page-driven source.

For sites whose per-event detail pages are not listed in sitemap.xml but ARE
linked from a JS-rendered listing/calendar page.  Workflow:

  1. Render the listing page via the scraper service (Playwright).
  2. Extract all <a href> links that match `url_pattern`.
  3. For each matched URL, render the detail page and extract the event from
     its JSON-LD schema.org Event block.

Optionally delegates detail-page parsing to a named parser from
`events.sources.detail_parsers` (same registry as SitemapSource) if
`parser_name` is set — useful for sites without JSON-LD.

Example job-params entry:

    {
      "name": "phila_gov",
      "listing_url": "https://www.phila.gov/the-latest/all-events/",
      "url_pattern": "/the-latest/events/[^/?#]+",
      "default_categories": ["philadelphia", "municipal"],
      "link_selector": "a",
      "render_wait_selector": ".tribe-events-calendar-list__event-title-link",
      "max_pages": 80,
      "concurrency": 4
    }
"""
from __future__ import annotations

import asyncio
import logging
import re
from urllib.parse import urljoin, urlparse

from bs4 import BeautifulSoup

from .base import RawEvent, Source
from .scraper import _iter_jsonld_events, _jsonld_to_raw, fetch_rendered_html

logger = logging.getLogger(__name__)

DEFAULT_MAX_PAGES = 80
DEFAULT_CONCURRENCY = 4


class ListingPageSource(Source):
    def __init__(
        self,
        name: str,
        listing_url: str,
        url_pattern: str,
        *,
        link_selector: str = "a",
        default_categories: list[str] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        concurrency: int = DEFAULT_CONCURRENCY,
        render_wait_selector: str | None = None,
        render_extra_wait_ms: int | None = None,
        detail_render_wait_selector: str | None = None,
        detail_render_extra_wait_ms: int | None = None,
        parser_name: str | None = None,
    ):
        self.name = name
        self.listing_url = listing_url
        self.url_pattern = re.compile(url_pattern)
        self.link_selector = link_selector
        self.default_categories = default_categories or []
        self.max_pages = min(max(1, int(max_pages)), 500)
        self.concurrency = max(1, min(int(concurrency), 16))
        self.render_wait_selector = render_wait_selector
        self.render_extra_wait_ms = render_extra_wait_ms
        self.detail_render_wait_selector = detail_render_wait_selector
        self.detail_render_extra_wait_ms = detail_render_extra_wait_ms

        self._parser = None
        if parser_name is not None:
            from .detail_parsers import parsers as DETAIL_PARSERS
            if parser_name not in DETAIL_PARSERS:
                raise ValueError(
                    f"unknown detail parser {parser_name!r}; "
                    f"available: {', '.join(sorted(DETAIL_PARSERS))}"
                )
            self._parser = DETAIL_PARSERS[parser_name]

        # Derive base URL for resolving relative hrefs.
        parsed = urlparse(listing_url)
        self._base_url = f"{parsed.scheme}://{parsed.netloc}"

    async def list_urls(self) -> list[str]:
        try:
            html, _ = await fetch_rendered_html(
                self.listing_url,
                wait_for_selector=self.render_wait_selector,
                extra_wait_ms=self.render_extra_wait_ms,
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "listing_page_fetch_failed",
                extra={"source": self.name, "url": self.listing_url, "error": str(exc)},
            )
            return []

        soup = BeautifulSoup(html, "html.parser")
        seen: set[str] = set()
        unique: list[str] = []
        for a in soup.select(self.link_selector):
            href = a.get("href") or ""
            href = href.strip()
            if not href or href.startswith(("#", "mailto:", "tel:")):
                continue
            full = urljoin(self._base_url, href)
            # Strip fragment.
            full = full.split("#")[0].rstrip("/")
            if not self.url_pattern.search(full):
                continue
            if full not in seen:
                seen.add(full)
                unique.append(full)

        logger.info(
            "listing_page_urls_found",
            extra={"source": self.name, "count": len(unique)},
        )
        return unique[: self.max_pages]

    async def _scrape_one(self, url: str, sem: asyncio.Semaphore) -> RawEvent | None:
        async with sem:
            try:
                html, fetched_url = await fetch_rendered_html(
                    url,
                    wait_for_selector=self.detail_render_wait_selector,
                    extra_wait_ms=self.detail_render_extra_wait_ms,
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "listing_detail_fetch_failed",
                    extra={"source": self.name, "url": url, "error": str(exc)},
                )
                return None

            # Named parser takes priority (e.g. for sites without JSON-LD).
            if self._parser is not None:
                try:
                    return self._parser(html, fetched_url, self.default_categories, self.name)
                except Exception as exc:  # noqa: BLE001
                    logger.warning(
                        "listing_detail_parser_failed",
                        extra={"source": self.name, "url": url, "error": str(exc)},
                    )
                    return None

            # Default: JSON-LD extraction (works for WP + The Events Calendar, etc.)
            nodes = _iter_jsonld_events(html)
            for node in nodes:
                raw = _jsonld_to_raw(node, self.name, self.default_categories, fetched_url)
                if raw is not None:
                    return raw

            logger.info(
                "listing_detail_no_event_found",
                extra={"source": self.name, "url": url},
            )
            return None

    async def fetch(self) -> list[RawEvent]:
        urls = await self.list_urls()
        if not urls:
            return []
        sem = asyncio.Semaphore(self.concurrency)
        results = await asyncio.gather(*(self._scrape_one(u, sem) for u in urls))
        return [r for r in results if r is not None]

    async def diagnose(self) -> dict[str, str]:
        try:
            urls = await self.list_urls()
        except Exception as exc:  # noqa: BLE001
            return {"_error": f"listing fetch failed: {type(exc).__name__}: {exc}"}
        if not urls:
            return {
                "matched_urls": "0",
                "_note": f"no links matched pattern {self.url_pattern.pattern!r}",
            }

        first = urls[0]
        try:
            html, fetched_url = await fetch_rendered_html(
                first,
                wait_for_selector=self.detail_render_wait_selector,
                extra_wait_ms=self.detail_render_extra_wait_ms,
            )
        except Exception as exc:  # noqa: BLE001
            return {
                "matched_urls": str(len(urls)),
                "first_url": first,
                "_error": f"detail fetch failed: {type(exc).__name__}: {exc}",
            }
        nodes = _iter_jsonld_events(html)
        raw = None
        if nodes:
            raw = _jsonld_to_raw(nodes[0], self.name, self.default_categories, fetched_url)
        return {
            "matched_urls": str(len(urls)),
            "max_pages_cap": str(self.max_pages),
            "concurrency": str(self.concurrency),
            "first_url": first,
            "first_html_chars": str(len(html)),
            "first_jsonld_events": str(len(nodes)),
            "first_parsed_title": (raw.title if raw else "(no JSON-LD Event or parser returned None)"),
            "first_parsed_start": (raw.start_time.isoformat() if raw and raw.start_time else "-"),
            "first_parsed_venue": (raw.venue_name or "-") if raw else "-",
        }
