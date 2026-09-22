"""Macaroni KID event-detail page parser.

Per-event pages on `*.macaronikid.com/events/<id>/<slug>` are server-rendered
HTML with stable class names:

    h1                    → title
    .startDate            → "May 14, 2026"
    .startTime            → "10:30 am - 11:45 am"
    .location-name        → venue name
    .location-address     → "<street>, <city> <state> <zip> <phone> Google Map"
                            (we strip the Google Map suffix + trailing phone)

No JSON-LD present, but the data is consistent enough to handle generically.
"""
from __future__ import annotations

import hashlib
import logging
import re

from bs4 import BeautifulSoup

from ...date_parsing import combine_date_and_time, parse_human_date
from ..base import RawEvent

logger = logging.getLogger(__name__)

_PHONE_RE = re.compile(r"\b\d{3}[-.\s]\d{3}[-.\s]\d{4}\b")


def _clean_address(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = text
    cleaned = re.sub(r"\s*Google Map\s*$", "", cleaned, flags=re.I).strip()
    cleaned = _PHONE_RE.sub("", cleaned).strip()
    cleaned = re.sub(r"\s{2,}", " ", cleaned).strip()
    return cleaned or None


def parse(html: str, url: str, default_categories: list[str], source_name: str) -> RawEvent | None:
    soup = BeautifulSoup(html, "html.parser")

    title_node = soup.find("h1")
    title = title_node.get_text(strip=True) if title_node else None
    if not title:
        logger.info("macaronikid_no_title", extra={"url": url})
        return None

    date_str = (soup.select_one(".startDate") or _Stub()).get_text(strip=True)
    time_str = (soup.select_one(".startTime") or _Stub()).get_text(strip=True)

    # Some events have date *ranges* like "March 27, 2026 - May 15, 2026" instead
    # of a single date (typically recurring series). Treat as: start = first day +
    # start-of-day-time, end = last day + end-of-day-time.
    start = end = None
    range_parts = re.split(r"\s+-\s+|\s+–\s+", date_str) if date_str else []
    if len(range_parts) == 2 and parse_human_date(range_parts[0]) and parse_human_date(range_parts[1]):
        start, _start_end = combine_date_and_time(range_parts[0], time_str or None)
        # Pair the *end* date with the *end* time-of-day for a sensible end_time.
        _end_start, end_combined = combine_date_and_time(range_parts[1], time_str or None)
        end = end_combined or parse_human_date(range_parts[1])
    else:
        start, end = combine_date_and_time(date_str or None, time_str or None)

    if start is None:
        logger.info("macaronikid_no_start_date", extra={"url": url, "raw_date": date_str})
        return None

    venue_node = soup.select_one(".location-name")
    venue = venue_node.get_text(" ", strip=True) if venue_node else None

    address_node = soup.select_one(".location-address")
    address = _clean_address(address_node.get_text(" ", strip=True) if address_node else None)

    # Description: try the most likely containers; fall back to none.
    desc_node = soup.select_one(".description, .event-description, .eventdesc")
    description = desc_node.get_text(" ", strip=True) if desc_node else None
    if description:
        description = re.sub(r"\s{2,}", " ", description)[:4000]

    # Stable source_event_id from the canonical URL (sitemap-derived).
    sid = url
    if "/events/" in url:
        # URLs look like /events/<24-hex>/<slug> — the 24-hex id is unique per occurrence.
        m = re.search(r"/events/([0-9a-f]{20,32})/", url)
        if m:
            sid = m.group(1)
    if not sid:
        sid = "hash:" + hashlib.sha1(f"{title}|{start.isoformat()}".encode()).hexdigest()[:24]

    return RawEvent(
        source=source_name,
        source_event_id=sid,
        title=title,
        description=description,
        start_time=start,
        end_time=end,
        venue_name=venue,
        venue_address=address,
        url=url,
        default_categories=list(default_categories),
        raw={"parser": "macaronikid", "raw_date": date_str, "raw_time": time_str},
    )


class _Stub:
    """Tiny BeautifulSoup-element-shaped stand-in for missing selectors."""
    def get_text(self, *_a, **_kw) -> str:
        return ""
