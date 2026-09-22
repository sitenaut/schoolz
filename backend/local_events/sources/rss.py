"""Generic RSS / Atom adapter for event feeds.

RSS for events is messy: there is no single standard for "event date". This
adapter looks for, in order of preference:

1. Common WordPress event-plugin fields parsed by feedparser as namespaced attrs:
   `ev_startdate`, `tribe_event_start_date`, `event_startdate`, `start_date`,
   `dc_date` (only when distinct from pubDate).
2. If none of those are present and the source config sets
   `treat_pubdate_as_start: true`, fall back to the entry's published date.
3. Otherwise the item is skipped (logged at WARNING with the entry title).

This keeps blog-style "what's happening this week" feeds from spamming the
events table with publish dates that have nothing to do with when the event
actually happens.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from time import struct_time
from typing import Any

import feedparser
import httpx

from ..date_parsing import combine_date_and_time
from .base import RawEvent, Source

logger = logging.getLogger(__name__)

EVENT_DATE_FIELDS = (
    "ev_startdate",
    "tribe_event_start_date",
    "event_startdate",
    "start_date",
)
EVENT_END_FIELDS = (
    "ev_enddate",
    "tribe_event_end_date",
    "event_enddate",
    "end_date",
)

# CivicPlus municipal sites (Cherry Hill, many other NJ/US townships) use a
# custom namespace with human-readable date + separate time-range strings.
# feedparser exposes namespaced fields as "<prefix>_<localname>" lowercased.
CIVICPLUS_DATE_FIELD = "calendarevent_eventdates"
CIVICPLUS_TIME_FIELD = "calendarevent_eventtimes"
CIVICPLUS_LOCATION_FIELD = "calendarevent_location"


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    s = value.strip()
    # feedparser sometimes gives 'YYYY-MM-DDTHH:MM:SS' without tz.
    try:
        # Try direct ISO parse first.
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except ValueError:
        pass
    return None


def _from_struct_time(t: struct_time | None) -> datetime | None:
    if t is None:
        return None
    try:
        return datetime(*t[:6], tzinfo=timezone.utc)
    except (TypeError, ValueError):
        return None


def _find_event_date(entry: Any, fields: tuple[str, ...]) -> datetime | None:
    for f in fields:
        val = entry.get(f) if hasattr(entry, "get") else getattr(entry, f, None)
        dt = _parse_iso(val)
        if dt is not None:
            return dt
    return None


# CivicPlus date/time parsing now lives in events.date_parsing as
# combine_date_and_time(), shared with the sitemap detail-page parsers.


def _stable_id(guid: str | None, link: str | None, title: str, dt: datetime) -> str:
    if guid:
        return guid
    if link:
        return link
    digest = hashlib.sha1(f"{title}|{dt.isoformat()}".encode("utf-8")).hexdigest()
    return f"hash:{digest[:24]}"


class RSSSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        default_categories: list[str] | None = None,
        treat_pubdate_as_start: bool = False,
        timeout: float = 30.0,
    ):
        self.name = name
        self.url = url
        self.default_categories = default_categories or []
        self.treat_pubdate_as_start = treat_pubdate_as_start
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(self.url, headers={"User-Agent": "schoolz-local-events/1.0"})
            resp.raise_for_status()
            body = resp.content

        feed = feedparser.parse(body)
        if feed.bozo and not feed.entries:
            err = getattr(feed, "bozo_exception", None)
            logger.warning("rss_parse_failed", extra={"source": self.name, "error": str(err)})
            return []

        out: list[RawEvent] = []
        for entry in feed.entries:
            try:
                title = (entry.get("title") or "").strip() or "(untitled)"

                # CivicPlus municipal feeds: human-readable date + separate time-range string.
                start, end = combine_date_and_time(
                    entry.get(CIVICPLUS_DATE_FIELD),
                    entry.get(CIVICPLUS_TIME_FIELD),
                )
                if start is None:
                    start = _find_event_date(entry, EVENT_DATE_FIELDS)
                    end = _find_event_date(entry, EVENT_END_FIELDS)
                if start is None and self.treat_pubdate_as_start:
                    start = _from_struct_time(entry.get("published_parsed")) \
                        or _from_struct_time(entry.get("updated_parsed"))
                if start is None:
                    logger.info(
                        "rss_entry_no_event_date",
                        extra={"source": self.name, "title": title[:80]},
                    )
                    continue

                description = entry.get("summary") or entry.get("description")
                link = entry.get("link") or None
                guid = entry.get("id") or entry.get("guid")
                location = (
                    entry.get(CIVICPLUS_LOCATION_FIELD)
                    or entry.get("ev_location")
                    or entry.get("location")
                    or None
                )
                image: str | None = None
                # RSS media-extension thumbnails come through as media_thumbnail / media_content.
                media_thumbs = entry.get("media_thumbnail") or []
                if media_thumbs:
                    image = media_thumbs[0].get("url")
                if not image:
                    media_content = entry.get("media_content") or []
                    if media_content:
                        image = media_content[0].get("url")

                out.append(
                    RawEvent(
                        source=self.name,
                        source_event_id=_stable_id(guid, link, title, start),
                        title=title,
                        description=description,
                        start_time=start,
                        end_time=end,
                        venue_name=location,
                        venue_address=location,
                        url=link,
                        image_url=image,
                        default_categories=list(self.default_categories),
                        raw={"guid": guid},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("rss_entry_skipped", extra={"source": self.name, "error": str(exc)})
                continue
        return out
