"""Parses a PTBoard (ptboard.com) PTA site's home page - confirmed real
(Haviland Avenue Elementary's haspta.ptboard.com/home): public, no login
needed, server-rendered (no Smore-style client JS wait needed beyond the
section wrapper appearing). The home page aggregates every active item
(forms & payments, announcements, signups, campaigns, open registration)
into `.content-summary-section` cards, each holding `.feed-item` rows with
a type tag, an optional timestamp/deadline, a title and a truncated
description - parsed generically across every section rather than one
parser per section type, since they all share this one row shape."""

import hashlib
from urllib.parse import urljoin

from bs4 import BeautifulSoup

import scraper_client

_WAIT_SELECTOR = ".content-summary-section"


def _content_hash(href: str) -> str:
    return hashlib.sha256(f"ptboard:{href}".encode()).hexdigest()


def _extract_feed_items(html: str, page_url: str) -> list[dict]:
    """Returns [{position, block_type, text_content, image_url, link_url,
    content_hash}], in document order - the same block shape
    smore_parser.py produces, so this reuses services/content_extractor.py
    unchanged."""
    soup = BeautifulSoup(html, "lxml")
    items = []
    for position, section in enumerate(soup.select(_WAIT_SELECTOR)):
        header = section.select_one(".header .left")
        section_name = header.get_text(strip=True) if header else None
        for row in section.select("a.feed-item"):
            raw_href = row.get("href")
            if not raw_href:
                continue
            href = urljoin(page_url, raw_href)
            type_tag = row.select_one(".type-tag")
            timestamp = row.select_one(".timestamp")
            title = row.select_one(".feed-title")
            desc = row.select_one(".feed-desc")
            parts = [p for p in (section_name, type_tag.get_text(strip=True) if type_tag else None) if p]
            label = " · ".join(parts)
            text_lines = [f"[{label}] {title.get_text(strip=True)}" if title else f"[{label}]"]
            if timestamp:
                text_lines.append(timestamp.get_text(strip=True))
            if desc:
                text_lines.append(desc.get_text(strip=True))
            text_content = " - ".join(text_lines)
            items.append(
                {
                    "position": position,
                    "block_type": "text",
                    "text_content": text_content,
                    "image_url": None,
                    "link_url": href,
                    "content_hash": _content_hash(href),
                }
            )
    return items


async def fetch_and_parse(url: str) -> list[dict]:
    result = await scraper_client.fetch_html(url, wait_for_selector=_WAIT_SELECTOR, timeout_ms=25_000)
    return _extract_feed_items(result["html"], url)
