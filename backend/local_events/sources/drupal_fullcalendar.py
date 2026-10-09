"""Drupal FullCalendar views that embed their whole event list in the page.

pennsaukenlibrary.org's /events renders a FullCalendar month grid, and the
module serialises *every* event the view holds into `drupalSettings.
fullCalendarView[0].calendar_options` (a JSON string) - about 2,700 of them
back to 2020, so only upcoming ones are kept. No scraper needed. Entries carry
a date (or datetime) and a linked title only: the time of day and description
live on each node page, which isn't fetched, so most come through as all-day.
`start` is local wall time.

Example job-params entry:

    {
      "name": "pennsauken_library",
      "url": "https://www.pennsaukenlibrary.org/events",
      "venue_name": "Pennsauken Free Public Library",
      "venue_address": "5605 Central Ave, Pennsauken, NJ 08109",
      "days_ahead": 120,
      "default_categories": ["pennsauken", "library"]
    }
"""
from __future__ import annotations

import html
import json
import logging
import re
from datetime import datetime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
DEFAULT_DAYS_AHEAD = 120
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_SETTINGS_RE = re.compile(r'<script type="application/json" data-drupal-selector="drupal-settings-json">(.*?)</script>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")


def _parse_start(value: str) -> tuple[datetime, bool] | None:
    try:
        if len(value) <= 10:
            return datetime.fromisoformat(value).replace(tzinfo=ET), True
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        return (parsed if parsed.tzinfo else parsed.replace(tzinfo=ET)), False
    except ValueError:
        return None


class DrupalFullCalendarSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        *,
        venue_name: str | None = None,
        venue_address: str | None = None,
        default_categories: list[str] | None = None,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        timeout: float = 30.0,
    ):
        self.name = name
        self.url = url
        self.venue_name = venue_name
        self.venue_address = venue_address
        self.default_categories = default_categories or []
        self.days_ahead = days_ahead
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            resp = await client.get(self.url)
            resp.raise_for_status()
        found = _SETTINGS_RE.search(resp.text)
        if not found:
            raise RuntimeError(f"{self.url} has no drupalSettings block")
        views = json.loads(found.group(1)).get("fullCalendarView") or []
        if not views:
            raise RuntimeError(f"{self.url} has no embedded FullCalendar view")
        options = json.loads(views[0]["calendar_options"])

        today = datetime.now(ET).replace(hour=0, minute=0, second=0, microsecond=0)
        horizon = today + timedelta(days=self.days_ahead)
        seen: set[str] = set()
        out: list[RawEvent] = []
        for e in options.get("events") or []:
            parsed = _parse_start(str(e.get("start") or ""))
            title = html.unescape(_TAG_RE.sub("", e.get("title") or "")).strip()
            if not parsed or not title:
                continue
            start, all_day = parsed
            if start < today or start > horizon:
                continue
            link = e.get("url")
            event_id = f"{e.get('eid') or link or title}:{start.isoformat()}"
            if event_id in seen:
                continue
            seen.add(event_id)
            end = _parse_start(str(e["end"]))[0] if e.get("end") and _parse_start(str(e["end"])) else None
            out.append(
                RawEvent(
                    source=self.name,
                    source_event_id=event_id,
                    title=title,
                    start_time=start,
                    end_time=end if end and end > start else None,
                    all_day=all_day,
                    venue_name=self.venue_name,
                    venue_address=self.venue_address,
                    url=urljoin(self.url, link) if link else None,
                    default_categories=list(self.default_categories),
                )
            )
        return out
