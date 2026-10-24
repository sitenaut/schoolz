"""Shared helpers for high-school SchoolClassYear rows - grad-year math and
lazy provisioning, used by both routers/class_years.py (read-time) and
services/hs_activities_site.py (extraction-time), so the two never
disagree about which four classes are "current" or what a class is called
by default.

Rows are provisioned lazily rather than created by an admin form: the
interesting per-class facts come out of extraction, not hand entry (see
docs/HS_CLASS_PAGES_DESIGN.md), so there's nothing for a form to do.
"""

from datetime import date

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
