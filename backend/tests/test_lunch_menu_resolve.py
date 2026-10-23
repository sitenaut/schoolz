import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import database
from models import District, LunchMenu, LunchMenuItem, School
from services.school_today import resolve_lunch_menu

_TZ = ZoneInfo("America/New_York")


def _day(y: int, m: int, d: int) -> datetime:
    return datetime(y, m, d, tzinfo=_TZ)


async def _menu(db, label: str, first: date, days: int, parsed: datetime, **owner) -> LunchMenu:
    menu = LunchMenu(meal_type="lunch", period_label=label, source_pdf_url=f"https://x.test/{uuid.uuid4().hex}.pdf", **owner)
    db.add(menu)
    await db.flush()
    menu.parsed_at = parsed
    for i in range(days):
        d = first + timedelta(days=i)
        db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=_day(d.year, d.month, d.day), description=f"{label} {i}"))
    await db.flush()
    return menu


@pytest.mark.anyio
async def test_next_month_posted_early_does_not_hide_this_month():
    # Chesterbrook: November's PDF, parsed Oct 19, was served all through late October.
    async with database.SessionLocal() as db:
        school = School(name=f"Preschool {uuid.uuid4().hex[:8]}", slug=f"pre-{uuid.uuid4().hex[:8]}")
        db.add(school)
        await db.flush()
        oct_ = await _menu(db, "October 2026", date(2026, 10, 1), 30, _day(2026, 10, 1), school_id=school.id)
        nov = await _menu(db, "November 2026", date(2026, 11, 2), 28, _day(2026, 10, 19), school_id=school.id)

        assert (await resolve_lunch_menu(db, school, on=date(2026, 10, 23))).id == oct_.id
        assert (await resolve_lunch_menu(db, school, on=date(2026, 11, 3))).id == nov.id
        # Between months (a weekend gap): the next one to start.
        assert (await resolve_lunch_menu(db, school, on=date(2026, 11, 1))).id == nov.id
        # Nothing current or upcoming: the latest parsed, as before.
        assert (await resolve_lunch_menu(db, school, on=date(2026, 12, 15))).id == nov.id


@pytest.mark.anyio
async def test_stale_school_menu_falls_back_to_a_current_district_menu():
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"District {tag}")
        db.add(district)
        await db.flush()
        school = School(name=f"Elementary {tag}", slug=f"el-{tag}", district_id=district.id, school_type="elementary")
        db.add(school)
        await db.flush()
        await _menu(db, "SchoolCafé", date(2026, 10, 1), 13, _day(2026, 10, 13), school_id=school.id)
        current = await _menu(db, "October 2026", date(2026, 10, 1), 30, _day(2026, 10, 1), district_id=district.id, school_type="elementary")

        assert (await resolve_lunch_menu(db, school, on=date(2026, 10, 23))).id == current.id
