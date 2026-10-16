"""Per-entry filters that work on any source type, applied after fetch.

Town calendars mix the events a family would go to (tree lightings, rec
sign-ups, shred days) with the town's own business: council and board
meetings, work sessions, court sessions. On some feeds that is most of the
calendar (Cinnaminson's Google Calendar: ~300 of 540 entries are board
meetings), so a municipal entry sets `skip_meetings` rather than every
source type growing its own filter. `exclude_title_patterns` is the same
thing with the entry's own regexes, for one-off junk ("R1 760 8-4").

Office closures ("Municipal Offices Closed for Thanksgiving") are kept on
purpose: parents plan around them.
"""
from __future__ import annotations

import logging
import re

from .prune import SOURCE_KEYS
from .sources.base import RawEvent

logger = logging.getLogger(__name__)

# Grouped alternations throughout - see the Categories note in
# docs/LOCAL_EVENTS_SOURCES.md for what an ungrouped `\ba|b\b` does.
MEETING_PATTERN = re.compile(
    r"\b(?:meeting|work\s*session|caucus|reorgani[sz]ation|public\s+hearing)s?\b"
    r"|\b(?:municipal|day|night|traffic)\s+court\b"
    r"|^[\w .'&-]+\s+court$",
    re.I,
)
# Meetings a resident would actually go to. Checked before MEETING_PATTERN.
KEEP_PATTERN = re.compile(r"\b(?:town\s*hall|community|open\s+house|information(?:al)?|info)\s+(?:meeting|session)s?\b", re.I)


def _title_filter(entry: dict) -> list[re.Pattern] | None:
    patterns: list[re.Pattern] = []
    for raw in entry.get("exclude_title_patterns") or []:
        try:
            patterns.append(re.compile(str(raw), re.I))
        except re.error as exc:
            # A typo in one entry's regex shouldn't fail the whole run.
            logger.warning("local_events_bad_exclude_pattern", extra={"source": entry.get("name"), "pattern": raw, "error": str(exc)})
    if entry.get("skip_meetings"):
        patterns.append(MEETING_PATTERN)
    return patterns or None


def filters_by_source(params: dict | None) -> dict[str, list[re.Pattern]]:
    """{source name: patterns} for every entry in params that sets a filter."""
    out: dict[str, list[re.Pattern]] = {}
    for key in SOURCE_KEYS:
        for entry in (params or {}).get(key) or []:
            if isinstance(entry, dict) and entry.get("name"):
                patterns = _title_filter(entry)
                if patterns:
                    out[str(entry["name"])] = patterns
    return out


def is_excluded(title: str, patterns: list[re.Pattern]) -> bool:
    for pattern in patterns:
        if pattern is MEETING_PATTERN and KEEP_PATTERN.search(title):
            continue
        if pattern.search(title):
            return True
    return False


def apply_filters(raws: list[RawEvent], patterns: list[re.Pattern] | None) -> tuple[list[RawEvent], int]:
    """Returns (kept, how many were dropped)."""
    if not patterns:
        return raws, 0
    kept = [raw for raw in raws if not is_excluded(raw.title.strip(), patterns)]
    return kept, len(raws) - len(kept)
