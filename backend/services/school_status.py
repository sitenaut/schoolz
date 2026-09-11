"""Shared "is this a no-school/half-day/delay day" detection, used by
both school_today.py (classifying a day's status) and content_extractor.py
(forcing these to scope="district" regardless of which school's newsletter
reported them - see is_status_title's docstring). Kept in one place so the
two never drift out of sync, which would silently reintroduce the class of
duplicate/miscounted-day bug this module exists to prevent."""

import re

CLOSED_RE = re.compile(r"\b(schools?|district)\s+closed\b|\bno school\b|\bclosed\b|\bin-?service\b|\bconference\b", re.I)
EARLY_RE = re.compile(r"\bearly\s+dismissal\b|\bhalf[\s-]day\b", re.I)
DELAY_RE = re.compile(r"\bdelayed\s+opening\b|\b\d\s*-?\s*hour\s+delay\b", re.I)


def is_status_title(title: str) -> bool:
    """True for a title that's fundamentally a school-day-status fact
    (closed, half day, delayed opening) rather than ordinary school-
    specific content. These are never really "this one school's" news -
    Cherry Hill's calendar is shared, so every school is closed/early-
    dismissed/delayed on the same day - even when one school's own
    newsletter phrases it with a school-specific detail (a particular
    early-dismissal time)."""
    return bool(CLOSED_RE.search(title) or EARLY_RE.search(title) or DELAY_RE.search(title))
