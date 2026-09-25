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

CLASSES_CATEGORY = "classes-&-lessons"  # the Local page labels it "Classes & Lessons"

KEYWORD_CATEGORIES: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"\b(kid|kids|children|child|family)\b", re.I), "family"),
    (re.compile(r"\b(kid|kids|children|child)\b", re.I), "kids"),
    (re.compile(r"\bteen(s|ager)?\b", re.I), "teen"),
    (re.compile(r"\bfree\b|\bno cost\b", re.I), "free"),
    # Each alternation is wrapped in (?:...) so \b applies to every word -
    # without it, r"\bsport|game|race|run\b" matched "race" inside "brace"
    # and "art" inside "start"/"party", tagging most of the feed arts/sports.
    (re.compile(r"\b(?:outdoors?|parks?|nature|trails?|festivals?)\b", re.I), "outdoor"),
    (re.compile(r"\b(?:library|story ?time|books?)\b", re.I), "library"),
    (re.compile(r"\b(?:music|concerts?|band|symphony)\b", re.I), "music"),
    (re.compile(r"\b(?:sports?|games?|races?|run|running)\b", re.I), "sports"),
    (re.compile(r"\b(?:museums?|art|arts|gallery|galleries|exhibits?)\b", re.I), "arts"),
    (re.compile(r"\bpersonal train(?:ing|er|ers)\b", re.I), "exercise"),
]

# "Classes & Lessons": one umbrella for anything you sign up to learn, so a
# filter doesn't mean picking "piano" and "cello" and "violin" separately.
# Overlaps freely with other categories. The title is trusted; a description
# is prose - a musician's bio says "began piano lessons at 3" or "prepared
# 800 lessons", a concert blurb "over the course of" - so there it takes
# sign-up wording: The Philadelphia School's bare "Cello"/"Piano" rows say
# "Lessons will be scheduled...".
_CLASS_TITLE_RE = re.compile(
    r"\b(?:lessons?|class(?:es)?|courses?|training)\b"
    r"(?<!world-class)(?<!first-class)(?<!middle class)(?<!working class)"
    r"(?<!golf course)(?<!obstacle course)(?<!race course)(?! of \d)",
    re.I,
)
_CLASS_DESCRIPTION_RE = re.compile(
    r"\b(?:lessons|classes) (?:will be|are|is) (?:scheduled|offered|held|available)"
    r"|\b(?:sign up|register|enroll)(?:ing)?(?: for)? (?:the |this |our |a )?(?:lessons?|class(?:es)?|course)\b",
    re.I,
)

# Source-supplied categories that mean the same thing (Evvnt's, and the
# Yodel source's mapping of its "Classes/Workshops").
_CLASS_ALIASES = {"classes-/-courses", "class", "workshops"}


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
    if CLASSES_CATEGORY not in found and (
        _CLASS_TITLE_RE.search(title)
        or _CLASS_DESCRIPTION_RE.search(description or "")
        or _CLASS_ALIASES & set(found)
    ):
        found.append(CLASSES_CATEGORY)
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
