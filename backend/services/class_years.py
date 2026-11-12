"""Shared helpers for high-school SchoolClassYear rows - grad-year math and
lazy provisioning, used by both routers/class_years.py (read-time) and
services/hs_activities_site.py (extraction-time), so the two never
disagree about which four classes are "current" or what a class is called
by default.

Rows are provisioned lazily rather than created by an admin form: the
interesting per-class facts come out of extraction, not hand entry (see
docs/HS_CLASS_PAGES_DESIGN.md), so there's nothing for a form to do.
"""

import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import SchoolClassYear

# Sources that belong to a class page rather than the general school view -
# shared by routers/schools.py (excludes them from the school's own
# /content and the general /calendar by default) and routers/class_years.py
# (always includes them). See docs/HS_CLASS_PAGES_DESIGN.md: a school's own
# activities calendar/announcements run to dozens of club-meeting-level
# items a week, which is exactly the "too much detail for a general view"
# case a per-class page exists to absorb - but the class page itself
# always wants to see all three.
CLASS_PAGE_SOURCES = ("hs_activities_site", "hs_announcements", "school_ics")

# 1=senior (graduates at the end of the CURRENT academic year) through
# 4=freshman (graduates in 4 more Junes) - matches the same Jul-Jun
# school-year boundary used throughout this codebase (marking periods,
# CourseDisplayPreference's academic-year keying, etc).
_LABELS = {1: "Seniors", 2: "Juniors", 3: "Sophomores", 4: "Freshmen"}
# How many classes past the seniors and before the freshmen a page reached by
# URL still resolves for (page_years).
PAGE_YEARS_EITHER_SIDE = 6


def academic_year_start(reference: date | None = None) -> int:
    reference = reference or date.today()
    return reference.year if reference.month >= 7 else reference.year - 1


def current_grad_years(reference: date | None = None) -> list[int]:
    """The four classes currently enrolled, seniors first - e.g. on
    2026-09-23 this is [2027, 2028, 2029, 2030], the exact four Cherry
    Hill East's own activities site nav lists."""
    start = academic_year_start(reference)
    return [start + 1, start + 2, start + 3, start + 4]


def default_label(grad_year: int, reference: date | None = None) -> str:
    """"Class of {year}" for a class that isn't currently 9th-12th grade
    (already graduated, or not yet in high school) - a class page reached
    directly by URL should never claim a grade level that's wrong."""
    start = academic_year_start(reference)
    return _LABELS.get(grad_year - start, f"Class of {grad_year}")


def page_years(reference: date | None = None) -> range:
    """The classes a page reached by URL may be created for: the four
    enrolled, recent graduates, and the next classes coming up. A public GET
    creates the row, so a crawler walking /class-years/1..5000 must not
    leave thousands of rows behind."""
    years = current_grad_years(reference)
    return range(years[0] - PAGE_YEARS_EITHER_SIDE, years[-1] + PAGE_YEARS_EITHER_SIDE + 1)


# Which class an item is for. Only the class pages' own sources used to say
# (a class-of-2027 sub-page's URL, an announcement's stated audience), so
# every newsletter's and calendar's "Class of 2028 Senior Trip" reached every
# family's calendar and family feed as whole-school news.

# The words a school's text uses for a class, as an index into
# current_grad_years (seniors first).
GRADE_WORD_TO_INDEX = {
    "freshman": 3, "freshmen": 3, "9th": 3, "9th grade": 3, "9th graders": 3,
    "sophomore": 2, "sophomores": 2, "10th": 2, "10th grade": 2, "10th graders": 2,
    "junior": 1, "juniors": 1, "11th": 1, "11th grade": 1, "11th graders": 1,
    "senior": 0, "seniors": 0, "12th": 0, "12th grade": 0, "12th graders": 0,
}

_ET = ZoneInfo("America/New_York")
# A two-digit year needs its apostrophe ("Class of '28"): "a class of 30" is
# a head count.
_YEAR = r"(?:20\d\d|['‘’]\d\d)"
# "Class of 2028", "Classes of 2027 and 2028", "Class of 2028 & 2029",
# "Classes of 2027, 2028, and 2029", "Class of 2027/2028".
_CLASS_OF_RE = re.compile(rf"\bclass(?:es)?\s+of\s+({_YEAR}(?:\s*(?:,?\s*(?:and|&)|,|/|\+)\s*{_YEAR})*)", re.IGNORECASE)
# A senior trip is the class graduating that year: "2027 Senior Trip", "Senior Trip 2028".
_SENIOR_TRIP_RE = re.compile(r"\b(20\d\d)\s+senior\s+trip\b|\bsenior\s+trip\s+(20\d\d)\b", re.IGNORECASE)


def local_day(value: date | None) -> date | None:
    """An item's date in the school's own time zone (a 7pm event is stored
    as midnight UTC the next day)."""
    if isinstance(value, datetime):
        return (value.astimezone(_ET) if value.tzinfo else value).date()
    return value


def _enrolled(years: set[int], reference: date | None) -> list[int] | None:
    return sorted(years & set(current_grad_years(local_day(reference)))) or None


def grad_years_in_title(title: str | None, reference: date | None = None) -> list[int] | None:
    """The enrolled classes a title names outright, or None for the whole
    school. `reference` is the item's date: the four classes are the ones
    enrolled then. Any other year is dropped, so an alumni reunion, an
    incoming class's information night, or a feed's stale "Class of 2026"
    row stays whole-school."""
    if not title:
        return None
    found: set[int] = set()
    for m in _CLASS_OF_RE.finditer(title):
        found.update(int(y[-2:]) + 2000 if len(y) < 4 else int(y) for y in re.findall(_YEAR, m.group(1)))
    for m in _SENIOR_TRIP_RE.finditer(title):
        found.add(int(m.group(1) or m.group(2)))
    return _enrolled(found, reference)


def grades_to_grad_years(grades: object, reference: date | None = None) -> list[int] | None:
    """A model's stated audience (["juniors"], ["10th graders", "11th
    graders"]) as the enrolled classes it means; None when it names none."""
    if not isinstance(grades, list):
        return None
    years = current_grad_years(local_day(reference))
    words = {g.strip().lower() for g in grades if isinstance(g, str)}
    return _enrolled({years[GRADE_WORD_TO_INDEX[w]] for w in words if w in GRADE_WORD_TO_INDEX}, reference)


async def _insert_if_missing(db: AsyncSession, school_id: str, grad_year: int) -> None:
    # Two first visits at once both find no row; the second insert must not 500.
    await db.execute(
        pg_insert(SchoolClassYear)
        .values(school_id=school_id, grad_year=grad_year)
        .on_conflict_do_nothing(constraint="uq_school_class_year")
    )


async def ensure_current_class_years(db: AsyncSession, school_id: str) -> list[SchoolClassYear]:
    """Lazily creates the four in-progress classes' rows the first time
    they're asked for - mirrors the _ensure_*_job convention used
    elsewhere in this codebase (routers/schools.py), just for a plain row
    instead of a ScheduledJob. Returns them in senior-first order."""
    years = current_grad_years()
    query = select(SchoolClassYear).where(SchoolClassYear.school_id == school_id, SchoolClassYear.grad_year.in_(years))
    by_year = {c.grad_year: c for c in (await db.execute(query)).scalars().all()}
    missing = [y for y in years if y not in by_year]
    if missing:
        for year in missing:
            await _insert_if_missing(db, school_id, year)
        by_year = {c.grad_year: c for c in (await db.execute(query)).scalars().all()}
    return [by_year[y] for y in years]


async def get_or_create_class_year(db: AsyncSession, school_id: str, grad_year: int) -> SchoolClassYear:
    query = select(SchoolClassYear).where(SchoolClassYear.school_id == school_id, SchoolClassYear.grad_year == grad_year)
    row = (await db.execute(query)).scalar_one_or_none()
    if row:
        return row
    await _insert_if_missing(db, school_id, grad_year)
    return (await db.execute(query)).scalar_one()
