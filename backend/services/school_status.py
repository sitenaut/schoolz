"""Shared "is this a no-school/half-day/delay day" detection, used by
both school_today.py (classifying a day's status) and content_extractor.py
(forcing these to scope="district" regardless of which school's newsletter
reported them - see is_status_title's docstring). Kept in one place so the
two never drift out of sync, which would silently reintroduce the class of
duplicate/miscounted-day bug this module exists to prevent."""

import re

# The closure words, for taking them out of a title (district_calendar_pdf).
# Whether a title says the school is closed is says_closed's job: this also
# matches an office or a gym being closed.
CLOSED_RE = re.compile(r"\b(schools?|district)\s+closed\b|\bno school\b|\bclosed\b|\bno students\b|\bin[\s-]?service\b|\bconference\b", re.I)
# A time before "Dismissal" is a short day when it falls from 10:00 to 2:00
# ("12:50 Dismissal", "1pm Dismissal", Palmyra's "2 PM Dismissal"), not a
# regular one ("2:30pm Dismissal") or a preschool-only one. "1/2 Day -
# District" is Paulsboro's half day. Mirrored in
# school_today._EARLY_RE and districtItems.ts HALF_DAY_RE.
EARLY_RE = re.compile(r"\bearly\s+dismiss(?:al)?\b|\bhalf[\s-]days?\b|\b(?:single|one)[\s-]session\b|\b\d\s*-?\s*hour\s+day\b|(?:\b1/2|½)\s*-?\s*day\b|(?:^|[^\d:])(?:1[0-2]|1|2(?!:[1-5]\d))(?::[0-5]\d)?\s*(?:[ap]\.?m\.?)?\s*(?:student\s+)?dismissal\b(?!.*\bpre-?schools?\b)", re.I)
DELAY_RE = re.compile(r"\bdelayed\s+opening\b|\b\d\s*-?\s*hour\s+delay\b", re.I)
# Staff days and conference days: status facts, but not closures of the day
# (school_today's classify_day doesn't count them).
STAFF_DAY_RE = re.compile(r"\bin[\s-]?service\b|\bconference\b", re.I)

# "Closed" that belongs to something other than the school day. Real titles:
# "OFFICE CLOSED", "GYM 2 CLOSED FOR REPAIRS", "Genesis Parent & Student
# Portals Closed for Summer Maintenance", "Weight Room Closed", "Board of
# Education Meeting - Executive (Closed) Session". Most real closures say
# only "closed" ("CLOSED - Winter Recess", "Columbus Day, Closed"), so a bare
# "closed" still counts once these are taken out. Mirrored in
# frontend/src/lib/districtItems.ts.
NOT_THE_SCHOOL_CLOSED_RE = re.compile(
    r"\b(?:main\s+|front\s+)?(?:offices?|portals?|gym(?:nasium)?(?:\s+\d+)?|weight\s+room|library|media\s+center|pool"
    r"|fields?|cafeteria|kitchen|parking\s+lot|playground|track|store|pantry|labs?)\s+(?:is\s+|are\s+|will\s+be\s+)?closed\b"
    r"|\(?\bclosed\)?\s+session\b",
    re.I,
)
# A school word earlier in the same clause makes it the school after all:
# "Schools & Offices Closed, Winter Recess", "Juneteenth - School/Offices Closed".
# Not Palmyra's summer "District Offices Closed" or Pitman's "School Offices Closed". Glassboro's in-service
# days are "Teacher Inservice - Students Off".
_SCHOOL_CLOSED_RE = re.compile(r"\b(?:schools?(?!\s+offices?\b)|district(?!\s+offices?\b)|buildings?)\b[^,;:()\u2013\u2014-]{0,40}?\bclosed\b|\bno school\b|\bno students\b|\bstudents\s+off\b", re.I)
_BARE_CLOSED_RE = re.compile(r"\bclosed\b", re.I)
# A title that is only the break's name ("Winter Recess", "Spring Break",
# "NJEA Convention",
# "Chews Spring Break", "Thanksgiving Recess (SC)") is a closed day: Riverton
# and Beverly put nothing else on those days. Not when it marks an edge of
# the break or a short day before it ("Spring Break Begins", "Return from
# Winter Break", "Winter Recess - Early Dismissal", "ONE SESSION WINTER RECESS").
_BREAK_RE = re.compile(
    r"^\s*(?:[\w'./]+:?\s+)?(?:winter|spring|fall|autumn|thanksgiving|holiday|mid-?winter|february)\s+(?:recess|break)\b"
    # NJ schools close by law for the NJEA convention: "NJEA Convention", "OFF TEACHERS CONVENTION".
    r"|\bNJEA\b|\bteachers?'?s?\s+convention\b",
    re.I,
)
_BREAK_EDGE_RE = re.compile(
    r"\b(?:begins?|starts?|ends?|over|returns?|reopens?|resumes?|last\s+day|dismissal|sessions?|half|1/2)\b", re.I
)


def _says_closed_outright(title: str) -> bool:
    return bool(_SCHOOL_CLOSED_RE.search(title) or _BARE_CLOSED_RE.search(NOT_THE_SCHOOL_CLOSED_RE.sub(" ", title)))


def is_break_only(title: str) -> bool:
    """A closure known only from the break's name. It yields to a half day
    on the same day: Gloucester Township's "Winter Recess" item starts on
    its single-session day."""
    return bool(
        _BREAK_RE.search(title) and not _BREAK_EDGE_RE.search(title) and not EARLY_RE.search(title)
        and not _says_closed_outright(title)
    )


def says_closed(title: str) -> bool:
    """True when a title says there's no school that day. Matching any
    "closed" made a newsletter's "Main Office Closed" a district-wide row
    (is_status_title) that closed every school's Today card."""
    return _says_closed_outright(title) or is_break_only(title)


def is_status_title(title: str) -> bool:
    """True for a title that's fundamentally a school-day-status fact
    (closed, half day, delayed opening) rather than ordinary school-
    specific content. These are never really "this one school's" news -
    Cherry Hill's calendar is shared, so every school is closed/early-
    dismissed/delayed on the same day - even when one school's own
    newsletter phrases it with a school-specific detail (a particular
    early-dismissal time)."""
    return bool(says_closed(title) or STAFF_DAY_RE.search(title) or EARLY_RE.search(title) or DELAY_RE.search(title))


# The boilerplate a status title wraps around its actual subject. Stripping
# it is what lets "No School - Yom Kippur" (a school's newsletter) be
# recognised as the same fact as "SCHOOLS CLOSED - Yom Kippur" (the district
# ics feed) - the two phrasings that produced a real duplicate pair on the
# calendar for both Yom Kippur and Labor Day.
_BOILERPLATE_RE = re.compile(
    r"\b(schools?\s+closed|district\s+closed|no\s+school|closed"
    r"|in[\s-]?service(\s+days?)?|conferences?"
    r"|early\s+dismissal|half[\s-]day|single[\s-]session(\s+days?)?|no\s+students|delayed\s+opening|\d\s*-?\s*hour\s+delay)\b",
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
    if says_closed(title) or STAFF_DAY_RE.search(title):
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
