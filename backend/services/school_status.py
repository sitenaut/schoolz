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


# The boilerplate a status title wraps around its actual subject. Stripping
# it is what lets "No School - Yom Kippur" (a school's newsletter) be
# recognised as the same fact as "SCHOOLS CLOSED - Yom Kippur" (the district
# ics feed) - the two phrasings that produced a real duplicate pair on the
# calendar for both Yom Kippur and Labor Day.
_BOILERPLATE_RE = re.compile(
    r"\b(schools?\s+closed|district\s+closed|no\s+school|closed"
    r"|in-?service(\s+days?)?|conferences?"
    r"|early\s+dismissal|half[\s-]day|delayed\s+opening|\d\s*-?\s*hour\s+delay)\b",
    re.I,
)
_PUNCT_RE = re.compile(r"[()\[\]{}:;,./–—-]+")


def status_kind(title: str) -> str | None:
    """Which kind of day-status a title describes, or None if it isn't one.

    Checks early/delay BEFORE closed, unlike school_today.py's classify_day,
    which deliberately lets closed win. That function is answering "what is
    this day?" (a closure outranks a half day); this one is answering "which
    fact is this?", where a real title like "EARLY DISMISSAL - Staff
    In-Service" must identify as an early dismissal - it matches CLOSED_RE
    too, via "in-service", and calling it a closure here would let it be
    merged with an actual closure on the same date.
    """
    if EARLY_RE.search(title):
        return "early"
    if DELAY_RE.search(title):
        return "delay"
    if CLOSED_RE.search(title):
        return "closed"
    return None


def status_subject(title: str) -> str | None:
    """The normalized subject of a status title ("yom kippur"), or None if
    the title isn't a status title at all. An empty string is a real result
    - a bare "SCHOOLS CLOSED" has no subject, and two of those on the same
    date are still the same fact."""
    if status_kind(title) is None:
        return None
    cleaned = _BOILERPLATE_RE.sub(" ", title)
    cleaned = _PUNCT_RE.sub(" ", cleaned)
    return " ".join(cleaned.lower().split())


def same_status_fact(a: str, b: str) -> bool:
    """True when two titles are the same day-status fact worded differently.

    Requires the same kind *and* the same subject, so a closure and an early
    dismissal that happen to share a subject ("SCHOOLS CLOSED - Thanksgiving"
    vs "EARLY DISMISSAL - Thanksgiving") are never merged. Deliberately
    stricter than matching on date alone: of the 8 same-date district pairs
    in one real three-month window, only 2 were genuine duplicates, and a
    date-only rule would have silently overwritten the other 6 with
    unrelated feed titles.
    """
    kind_a, kind_b = status_kind(a), status_kind(b)
    if kind_a is None or kind_a != kind_b:
        return False
    return status_subject(a) == status_subject(b)
