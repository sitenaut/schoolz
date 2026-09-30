"""Placewise mall sites (thepromenadenj.com - The Promenade at Sagemore).

The events page is a Next.js page that server-renders the whole current
event list into `__NEXT_DATA__` (pageProps.sectionsData.events_list_container),
so plain httpx is enough - no scraper.

Placewise's event list mixes real events with store promotions. A
`date_range` with no end date is a standing sale ("NEW YEAR, NEW JEANS" at
a store since January), not something on a day, so it's skipped. Timed
events carry real UTC instants; date ranges are all-day, with the mall's
own local-midnight bounds.

A page that no longer has the events container raises instead of returning
nothing, so a Placewise redesign shows up as a failed source (WARNING)
rather than a quiet "0 events".

Example job-params entry:

    {
      "name": "promenade_sagemore",
      "url": "https://thepromenadenj.com/events",
      "venue_name": "The Promenade at Sagemore",
      "venue_address": "500 Route 73 S, Marlton, NJ 08053",
      "default_categories": ["shopping"]
    }
"""
from __future__ import annotations

import html as html_lib
import json
import re
from datetime import datetime
from urllib.parse import urljoin, urlparse

import httpx

from .base import RawEvent, Source

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_events(
    page_html: str,
    page_url: str,
    source: str,
    *,
    venue_name: str | None = None,
    venue_address: str | None = None,
    default_categories: list[str] | None = None,
) -> list[RawEvent]:
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        raise ValueError("no __NEXT_DATA__ on the page - not a Placewise events page any more?")
    container = (
        json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("sectionsData", {}).get("events_list_container")
    )
    if not isinstance(container, dict) or not isinstance(container.get("events"), list):
        raise ValueError("no events_list_container in __NEXT_DATA__")

    origin = "{0.scheme}://{0.netloc}/".format(urlparse(page_url))
    out: list[RawEvent] = []
    for row in container["events"]:
        ev = (row or {}).get("event") or {}
        occurrence = ev.get("occurrence") or {}
        if ev.get("occurrence_type") == "date_range" and not occurrence.get("end_date"):
            continue
        start = _dt(ev.get("starts_at"))
        if start is None or not ev.get("id") or not ev.get("title"):
            continue
        store = (row or {}).get("store") or {}
        store_name = (store.get("name") or "").strip()
        venue = f"{store_name} at {venue_name}" if store_name and venue_name else (store_name or venue_name)
        description = " ".join(p for p in (_text(ev.get("headline")), _text(ev.get("body"))) if p) or None
        out.append(
            RawEvent(
                source=source,
                source_event_id=str(ev["id"]),
                title=_text(ev["title"]),
                description=description,
                start_time=start,
                end_time=_dt(ev.get("ends_at")),
                all_day=ev.get("occurrence_type") == "date_range",
                venue_name=venue,
                venue_address=venue_address,
                url=urljoin(origin, ev["url"]) if ev.get("url") else page_url,
                image_url=(ev.get("image") or {}).get("url"),
                default_categories=list(default_categories or []),
                raw={"placewise_id": ev["id"], "occurrence_type": ev.get("occurrence_type")},
            )
        )
    return out


class PlacewiseSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        *,
        venue_name: str | None = None,
        venue_address: str | None = None,
        default_categories: list[str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.url = url
        self.venue_name = venue_name
        self.venue_address = venue_address
        self.default_categories = default_categories or []
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            resp = await client.get(self.url)
            resp.raise_for_status()
        return parse_events(
            resp.text,
            str(resp.url),
            self.name,
            venue_name=self.venue_name,
            venue_address=self.venue_address,
            default_categories=self.default_categories,
        )
