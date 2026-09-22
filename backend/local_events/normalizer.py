"""RawEvent -> normalized fields suitable for the Event ORM upsert.

Responsibilities:
- Ensure timezone-aware start/end (assume America/New_York if naive).
- Strip HTML from description.
- Infer is_free from price_min == 0 or text keywords.
- Infer categories from title/description + the source's default_categories.
"""
from __future__ import annotations

import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from .sources.base import RawEvent

DEFAULT_TZ = ZoneInfo("America/New_York")

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")

KEYWORD_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(kid|kids|children|child|family)\b", re.I), "family"),
    (re.compile(r"\b(kid|kids|children|child)\b", re.I), "kids"),
    (re.compile(r"\bteen(s|ager)?\b", re.I), "teen"),
    (re.compile(r"\bfree\b|\bno cost\b", re.I), "free"),
    (re.compile(r"\boutdoor|park|nature|trail|festival\b", re.I), "outdoor"),
    (re.compile(r"\blibrary|story ?time|book\b", re.I), "library"),
    (re.compile(r"\bmusic|concert|band|symphony\b", re.I), "music"),
    (re.compile(r"\bsport|game|race|run\b", re.I), "sports"),
    (re.compile(r"\bmuseum|art|gallery|exhibit\b", re.I), "arts"),
]


def _strip_html(text: str | None) -> str | None:
    if not text:
        return None
    cleaned = _HTML_TAG_RE.sub(" ", text)
    cleaned = _WHITESPACE_RE.sub(" ", cleaned).strip()
    return cleaned or None


def _ensure_tz(dt: datetime | None) -> datetime | None:
    if dt is None:
        return None
    if dt.tzinfo is None:
        return dt.replace(tzinfo=DEFAULT_TZ)
    return dt


def _infer_categories(title: str, description: str | None, defaults: list[str]) -> list[str]:
    haystack = " ".join([title, description or ""]).strip()
    found: list[str] = list(defaults)
    for pattern, tag in KEYWORD_CATEGORIES:
        if pattern.search(haystack) and tag not in found:
            found.append(tag)
    return found


def _infer_is_free(price_min: float | None, title: str, description: str | None) -> bool | None:
    if price_min is not None:
        return price_min == 0
    haystack = " ".join([title, description or ""]).lower()
    if "free admission" in haystack or " free " in f" {haystack} ":
        return True
    return None


def normalize(raw: RawEvent) -> dict:
    """Return a dict ready to feed into an Event ORM insert/upsert."""
    description = _strip_html(raw.description)
    start = _ensure_tz(raw.start_time)
    end = _ensure_tz(raw.end_time)
    # Normalize to UTC for storage.
    if start is not None:
        start = start.astimezone(timezone.utc)
    if end is not None:
        end = end.astimezone(timezone.utc)
    categories = _infer_categories(raw.title, description, raw.default_categories)
    is_free = raw.is_free if raw.is_free is not None else _infer_is_free(raw.price_min, raw.title, description)
    return {
        "source": raw.source,
        "source_event_id": raw.source_event_id,
        "title": raw.title.strip()[:500],
        "description": description,
        "start_time": start,
        "end_time": end,
        "all_day": raw.all_day,
        "venue_name": raw.venue_name,
        "venue_address": raw.venue_address,
        "latitude": raw.latitude,
        "longitude": raw.longitude,
        "url": raw.url,
        "image_url": raw.image_url,
        "price_min": raw.price_min,
        "price_max": raw.price_max,
        "is_free": is_free,
        "categories": categories,
        "raw": raw.raw,
    }
