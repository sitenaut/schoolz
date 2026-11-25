"""A school newsletter's closure or short day against the district calendar's
own rows (content_extractor._calendar_says). Titles and dates are Cherry
Hill's, November 2026."""
import uuid
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest

import database
from models import District, SchoolContentItem
from services.content_extractor import _calendar_says
from services.school_status import break_name, day_kind
from services.school_today import _hours

_ET = ZoneInfo("America/New_York")


def _at(month: int, day: int, hour: int = 0, year: int = 2026) -> datetime:
    return datetime(year, month, day, hour, tzinfo=_ET)


async def _district(db) -> str:
    district = District(name=f"Calendar Says {uuid.uuid4().hex[:8]}")
    db.add(district)
    await db.flush()
    rows = [
        ("STUDENT EARLY DISMISSAL (PRESCHOOL-8): Pre-K, Elementary, and Middle Conferences", _at(11, 30), _at(12, 4), ["other", "elementary", "middle"]),
        ("SCHOOLS CLOSED - Thanksgiving Break", _at(11, 26), _at(11, 28), None),
        ("SCHOOLS CLOSED - Winter Break", _at(12, 24), _at(1, 2, year=2027), None),
        ("Board of Education meeting", _at(11, 24, 18), None, None),
    ]
    for title, start, end, types in rows:
        db.add(
            SchoolContentItem(
                scope="district", district_id=district.id, category="event", title=title, start_date=start, end_date=end,
                is_all_day=end is not None, source="district_ics", applies_to_school_types=types,
            )
        )
    await db.flush()
    return district.id


@pytest.mark.anyio
async def test_a_newsletters_retelling_of_a_calendar_day_is_a_duplicate():
    async with database.SessionLocal() as db:
        d = await _district(db)
        # Timed at 1 PM on the first of the calendar's four all-day days.
        assert await _calendar_says(db, d, "Parent-Teacher Conferences (Early Dismissal 1:00 PM)", _at(11, 30, 13), "elementary") == "duplicate"
        # The second day of a two-day closure, worded bare.
        assert await _calendar_says(db, d, "School Closed", _at(11, 27), "elementary") == "duplicate"
        assert await _calendar_says(db, d, "Winter Break", _at(12, 24), "high") == "duplicate"


@pytest.mark.anyio
async def test_a_day_the_calendar_gives_other_schools_stays_the_schools_own():
    async with database.SessionLocal() as db:
        d = await _district(db)
        assert await _calendar_says(db, d, "Early Dismissal for Finals Review", _at(12, 1), "high") == "other_schools"


@pytest.mark.anyio
async def test_a_break_on_dates_the_calendar_does_not_have_is_contradicted():
    async with database.SessionLocal() as db:
        d = await _district(db)
        assert await _calendar_says(db, d, "Winter Break", _at(12, 1), "elementary") == "contradicted"


@pytest.mark.anyio
async def test_news_the_calendar_does_not_have_goes_through():
    async with database.SessionLocal() as db:
        d = await _district(db)
        # A snow day, a short day of its own, a closure beside an evening meeting.
        assert await _calendar_says(db, d, "Schools Closed - Snow", _at(12, 10), "elementary") is None
        assert await _calendar_says(db, d, "Early Dismissal", _at(12, 23), "elementary") is None
        assert await _calendar_says(db, d, "School Closed", _at(11, 24), "elementary") is None
        # A break the calendar never names.
        assert await _calendar_says(db, d, "Spring Break", _at(3, 25, year=2027), "elementary") is None
        # Not about the school day at all.
        assert await _calendar_says(db, d, "Parent-Teacher Conferences", _at(11, 30, 13), "elementary") is None


def test_day_kind_and_break_name():
    assert day_kind("Parent-Teacher Conferences (Early Dismissal 1:00 PM)") == "early"
    assert day_kind("SCHOOLS CLOSED - Thanksgiving Break") == "closed"
    assert day_kind("Winter Break") == "closed"
    assert day_kind("Parent-Teacher Conferences") is None
    assert day_kind("IN-SERVICE") is None
    assert break_name("SCHOOLS CLOSED - Winter Break") == "winter"
    assert break_name("Mid-Winter Recess") == "midwinter"
    assert break_name("Board of Education meeting") is None


def test_a_short_day_with_no_time_on_file_shows_no_hours():
    school = SimpleNamespace(start_time="9:00 AM", end_time="3:30 PM", early_dismissal_time=None, delayed_opening_time=None)
    assert _hours(school, "open") == "9:00 AM–3:30 PM"
    assert _hours(school, "early_dismissal") is None
    assert _hours(school, "delayed") is None
    school.early_dismissal_time = "1:00 PM"
    assert _hours(school, "early_dismissal") == "9:00 AM–1:00 PM"
