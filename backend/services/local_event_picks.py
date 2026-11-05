"""Choosing local events to suggest without a model: the rule the chatbot's
find_local_events browses by (services/chatbot_personal.py) and the Today
page's day-off picks (GET /local-events/day-off).

Classes are usually paid (the Y's are member classes), and a weekend would
otherwise be mostly "Open Gym" and "Aqua Fit". Product rule: a class is
only shown with explicit evidence it costs nothing - never on "no price
listed", which for a class almost always means "ask at the desk".
"""

import re
from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from services.i18n import fold

ET = ZoneInfo("America/New_York")

CLASS_CATEGORIES = {"group-exercise", "open-gym", "gym", "pool", "swim", "fitness", "ymca", "child-care", "class", "classes-&-lessons", "exercise"}
_CLASS_TITLE_RE = re.compile(r"\b(class(es)?|lessons?|courses?|workshops?|clinics?|bootcamp)\b", re.I)
# "gluten-free", "sugar-free", "feel free", "free-throw" aren't about price.
_FREE_TEXT_RE = re.compile(
    r"(?<![-\w])(?<!feel )free\b(?!-)|\bno (cost|charge|fee)s?\b|\bcomplimentary\b|\bfree of charge\b"
    r"|\bwithout charge\b|\bat no cost\b|\$0(\.00)?\b",
    re.I,
)


def is_class(title: str, categories: Sequence[str]) -> bool:
    return bool(set(categories) & CLASS_CATEGORIES) or bool(_CLASS_TITLE_RE.search(title))


def is_explicitly_free(is_free: bool | None, price_max: float | None, title: str, description: str | None) -> bool:
    if is_free or (price_max is not None and float(price_max) == 0):
        return True
    return bool(_FREE_TEXT_RE.search(f"{title} {description or ''}"))


# Who the day off is for, by the schools that are out: the tags to look for.
# family/kids/teen are keyword-inferred (local_events/normalizer.py) and miss
# plenty, which is why the card also offers the chatbot, which reads every
# title. Teen events are few, so for teens they go first; for kids the tag
# says little (prod's "kids" is mostly library programs, "family" has the
# festivals and the mini golf), so distance decides.
DAY_OFF_TAGS = {"kids": ("kids", "family"), "teens": ("teen", "family")}
DAY_OFF_PICKS = 3
# A day off is a daytime problem: an evening event is still something to
# do, just not the answer to "what do we do all day"; a late one is no answer
# for kids at all (prod tags Philadelphia club shows "family" from their blurbs).
_EVENING_HOUR = 17
_LATE_HOUR = 19
# School's out for school-age kids; their little siblings' day is no different.
_UNDER_SCHOOL_AGE_RE = re.compile(r"\b(?:toddlers?|preschool(?:ers)?|pre-?k|bab(?:y|ies)|infants?)\b", re.I)
# How long an event with no end time is taken to run, for "still on today".
_ASSUMED_LENGTH = timedelta(hours=1)


def day_off(events: Sequence[Any], audience: str, still_on_at: datetime | None = None) -> tuple[list[Any], int]:
    """(the picks, how many qualified). `events` are rows already on the day,
    each with title, categories, description, is_free, price_max,
    start_time, end_time, all_day and miles. Daytime before evening, then
    (for teens) teen-tagged, then the nearest; a title once (a storytime at
    three library branches is one idea, at the nearest branch). `still_on_at`
    drops what has already finished, for today's card."""
    preferred = "teen" if audience == "teens" else None

    def hour(e: Any) -> int | None:
        return None if e.all_day else e.start_time.astimezone(ET).hour

    def ended(e: Any) -> bool:
        if still_on_at is None or e.all_day:
            return False
        return (e.end_time or e.start_time + _ASSUMED_LENGTH) <= still_on_at

    qualified = [
        e for e in events
        if not ended(e)
        and (hour(e) or 0) < _LATE_HOUR
        and not _UNDER_SCHOOL_AGE_RE.search(e.title)
        and (not is_class(e.title, e.categories) or is_explicitly_free(e.is_free, e.price_max, e.title, e.description))
    ]

    def evening(e: Any) -> bool:
        return (hour(e) or 0) >= _EVENING_HOUR

    ranked = sorted(qualified, key=lambda e: (evening(e), preferred is not None and preferred not in e.categories, e.miles, e.start_time))
    picks: list[Any] = []
    seen: set[str] = set()
    for e in ranked:
        key = fold(e.title).strip()
        if key in seen:
            continue
        seen.add(key)
        picks.append(e)
        if len(picks) == DAY_OFF_PICKS:
            break
    return picks, len(qualified)
