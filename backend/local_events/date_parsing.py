"""Shared date/time parsing helpers used by multiple source adapters.

Originally these lived in events.sources.rss for CivicPlus municipal feeds.
The Macaroni KID detail-page parser (sitemap source) needs the same shapes:
human-readable date ("May 16, 2026") + a separate time-range string
("08:00 AM - 10:00 AM"), combined into tz-aware datetimes.
"""
from __future__ import annotations

import re
from datetime import datetime
from zoneinfo import ZoneInfo

EASTERN = ZoneInfo("America/New_York")

_DATE_FORMATS = ("%B %d, %Y", "%b %d, %Y")
_TIME_RANGE_RE = re.compile(
    r"\s*(\d{1,2}:\d{2}\s*[APap][Mm])\s*(?:-|–|to)\s*(\d{1,2}:\d{2}\s*[APap][Mm])\s*"
)
_SINGLE_TIME_RE = re.compile(r"\s*(\d{1,2}:\d{2}\s*[APap][Mm])\s*")


def parse_human_date(date_str: str | None) -> datetime | None:
    """Parse 'May 16, 2026' style strings to a midnight-Eastern datetime."""
    if not date_str:
        return None
    s = date_str.strip()
    for fmt in _DATE_FORMATS:
        try:
            return datetime.strptime(s, fmt).replace(tzinfo=EASTERN)
        except ValueError:
            continue
    return None


def parse_time_range(time_str: str | None) -> tuple[str | None, str | None]:
    """Return (start, end) hh:mm AM/PM strings from inputs like '08:00 AM - 10:00 AM'."""
    if not time_str:
        return None, None
    m = _TIME_RANGE_RE.fullmatch(time_str.strip())
    if m:
        return m.group(1), m.group(2)
    m = _SINGLE_TIME_RE.fullmatch(time_str.strip())
    if m:
        return m.group(1), None
    return None, None


def combine_date_and_time(date_str: str | None, time_str: str | None) -> tuple[datetime | None, datetime | None]:
    """Combine a human date string and a time-range string into (start, end) tz-aware datetimes.

    Anchored to America/New_York since most of our sources are local-to-Cherry-Hill.
    """
    base = parse_human_date(date_str)
    if base is None:
        return None, None
    start_t, end_t = parse_time_range(time_str)
    start_dt = base
    end_dt: datetime | None = None
    if start_t:
        try:
            t = datetime.strptime(start_t.strip().upper(), "%I:%M %p")
            start_dt = base.replace(hour=t.hour, minute=t.minute)
        except ValueError:
            pass
    if end_t:
        try:
            t = datetime.strptime(end_t.strip().upper(), "%I:%M %p")
            end_dt = base.replace(hour=t.hour, minute=t.minute)
        except ValueError:
            pass
    return start_dt, end_dt
