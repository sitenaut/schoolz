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
    "ALL District Offices Closed",
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


def test_a_four_hour_day_is_a_half_day_status():
    # Edgewater Park words every early dismissal this way.
    assert is_status_title("4 Hour Day for Students") and is_status_title("4 Hour Day for All")


@pytest.mark.parametrize(
    "title",
    ["Winter Recess", "SPRING BREAK", "Chews Spring Break", "Thanksgiving Recess (SC)", "Spring Break April 15-22", "Winter Break  HAPPY HOLIDAYS",
     "NJEA Convention", "OFF TEACHERS CONVENTION", "NJEA Teacher's Convention"],
)
def test_a_title_that_is_only_the_break_closes_the_day(title):
    # Riverton's and Beverly's calendars put nothing else on those days.
    assert says_closed(title) and classify_day([title])[0] == "closed" and is_status_title(title)


@pytest.mark.parametrize(
    "title",
    ["Spring Break Begins", "Return from Winter Break", "Winter Recess Ends", "ONE SESSION WINTER RECESS",
     "1/2 DAY WINTER RECESS", "Recess Runners Fun Run", "Student Lunch and Recess Schedule", "Musical Set Break Down"],
)
def test_an_edge_of_a_break_or_a_recess_period_is_not_closed(title):
    assert not says_closed(title)


def test_a_short_day_before_a_break_is_an_early_dismissal():
    assert classify_day(["Winter Recess - Early Dismissal"])[0] == "early_dismissal"
    assert classify_day(["THANKSGIVING RECESS (EARLY DISMISSAL)"])[0] == "early_dismissal"


def test_a_half_day_wins_over_a_break_that_starts_that_day():
    # Gloucester Township's "Winter Recess" item starts on its single-session day.
    assert classify_day(["Winter Recess", "SINGLE SESSION DAY"])[0] == "early_dismissal"
    assert classify_day(["Winter Recess"]) == ("closed", "Winter Recess")


@pytest.mark.parametrize(
    "title",
    ["12:50 Dismissal", "1pm Dismissal", "2 PM Dismissal", "12:45 Dismissal Day", "Final Exams--12:00 pm dismissal",
     "Conferences/12:50 Dismissal", "12:09pm Student Dismissal (Staff PD 2:27pm Dismissal)", "1:00 PM  Dismissal - Students Only",
     "1/2 Day - District", "1/2 Day - Parent/Teacher Conf", "District ½ Day"],
)
def test_a_midday_dismissal_time_is_a_half_day(title):
    assert classify_day([title])[0] == "early_dismissal" and is_status_title(title)


@pytest.mark.parametrize(
    "title", ["Full Day of School - AHS ( 2:30pm Dismissal)", "3:20pm Dismissal Begins", "1:30 Dismissal All Preschools", "Dismissal Procedures"]
)
def test_a_regular_or_preschool_dismissal_time_is_not_a_half_day(title):
    assert classify_day([title])[0] == "open"
