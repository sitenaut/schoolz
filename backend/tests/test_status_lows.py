"""Bug sweep 2026-10-23 lows on school-day status: a long closure that began
more than a week ago (F53), and "closed" that belongs to an office or a gym
rather than the school (F58)."""
import os
import uuid
from datetime import date, datetime, timedelta

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest

import database
from models import District, School, SchoolContentItem, Student, StudentSpecial
from services.kids_schedule import upcoming_days
from services.school_status import is_status_title, says_closed
from services.school_today import LOCAL_TZ, build_today, classify_day

# Every title here is real: what the local copy of the feeds and newsletters
# holds that matches a bare "closed".
REAL_CLOSURES = [
    "CLOSED - Winter Recess",
    "Closed- Labor Day",
    "Columbus Day, Closed",
    "Thanksgiving Recess/Closed",
    "Closed for snow",
    "Closed/Staff In-Service",
    "School's Closed - President's Day",
    "Schools & Offices Closed, Winter Recess",
    "Labor Day Weekend, Schools and Offices Closed",
    "Juneteenth - School/Offices Closed",
    "School Buildings Closed/Independence Day Observance",
    "All School District Buildings Closed",
    "School - Closed: Winter Break",
    "School is Closed for Students",
    "HAS - Conferences - HAS Closed",
    "Shool Closed - MLK, Jr. Day",
    "SCHOOLS CLOSED - Labor Day",
    "No School - Yom Kippur",
]
NOT_THE_SCHOOL = [
    "OFFICE CLOSED",
    "HSD: Offices Closed (Juneteenth)",
    "GYM 2 CLOSED FOR REPAIRS",
    "Genesis Parent & Student Portals Closed for Summer Maintenance",
    "Weight Room Closed",
    "Board of Education Meeting - Executive (Closed) Session",
    "Main Office Closed",
    "Library Closed for Inventory",
]


@pytest.mark.parametrize("title", REAL_CLOSURES)
def test_real_closures_still_close_the_day(title):
    assert says_closed(title) and classify_day([title])[0] == "closed" and is_status_title(title)


@pytest.mark.parametrize("title", NOT_THE_SCHOOL)
def test_an_office_or_a_gym_being_closed_is_not_a_closed_day(title):
    assert not says_closed(title) and classify_day([title])[0] == "open" and not is_status_title(title)


def _day(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), LOCAL_TZ)


@pytest.mark.anyio
async def test_a_recess_that_began_weeks_ago_still_closes_the_schedule():
    run = uuid.uuid4().hex[:8]
    today = date(2026, 12, 31)  # a Thursday, inside a recess that began Dec 21
    async with database.SessionLocal() as db:
        district = District(name=f"Recess District {run}")
        db.add(district)
        await db.flush()
        school = School(name=f"Recess Elementary {run}", slug=f"recess-{run}", school_type="elementary", district_id=district.id)
        db.add(school)
        await db.flush()
        student = Student(first_name="Ava", last_name="R", student_id=f"r-{run}", school_id=school.id, match_key=f"ava|r|r-{run}")
        db.add(student)
        await db.flush()
        db.add(StudentSpecial(student_id=student.id, rotation_day=1, subject="Art"))
        common = dict(scope="district", district_id=district.id, is_current=True, is_all_day=True, source="ics_feed")
        db.add(SchoolContentItem(
            title="SCHOOLS CLOSED - Winter Recess", category="event",
            start_date=_day(date(2026, 12, 21)), end_date=_day(date(2027, 1, 2)), **common,
        ))
        for n, d in enumerate([date(2027, 1, 4), date(2027, 1, 5)], start=1):
            db.add(SchoolContentItem(title=f"Day {n}", category="event", start_date=_day(d), **common))
        # Began weeks ago and still running, but not a closure: stays off the schedule.
        db.add(SchoolContentItem(
            title="Coat drive", category="initiative",
            start_date=_day(today - timedelta(days=20)), end_date=_day(today + timedelta(days=5)), **common,
        ))
        await db.commit()

        days = await upcoming_days(db, school, student.id, today, 2)
        assert [d["date"] for d in days] == ["2027-01-04", "2027-01-05"]
        assert (await build_today(db, school, today)).status == "closed"
