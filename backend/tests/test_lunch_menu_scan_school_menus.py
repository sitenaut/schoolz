import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from sqlalchemy import select

import database
from models import District, LunchMenu, LunchMenuItem, School
from scheduler.jobs import lunch_menu_scan
from services.school_today import resolve_lunch_menu

_TZ = ZoneInfo("America/New_York")


@pytest.mark.anyio
async def test_a_menu_named_for_one_school_is_stored_for_that_school_and_served_to_it(monkeypatch):
    """Swedesboro-Woolwich: three schools share the ELEM menu and Hill has its own."""
    tag = uuid.uuid4().hex[:8]
    month = datetime.now(_TZ).month
    async with database.SessionLocal() as db:
        district = District(name=f"Menu District {tag}", food_services_menu_url="https://x.test/menus")
        db.add(district)
        await db.flush()
        shared = School(name=f"Shared School {tag}", slug=f"shared-{tag}", district_id=district.id, school_type="elementary")
        hill = School(name=f"Hill School {tag}", slug=f"hill-{tag}", district_id=district.id, school_type="elementary")
        db.add_all([shared, hill])
        await db.commit()
        district_id, hill_id = district.id, hill.id

    seen = {}

    async def discover(page_url, school_types=None, schools=None):
        seen["schools"] = sorted(s["name"].split()[0] for s in schools)
        label = datetime(2026, month, 1).strftime("%B 2026")
        return [
            {"school_type": "elementary", "meal_type": "lunch", "period_label": label, "pdf_url": "https://x.test/ELEM.pdf"},
            {"school_type": "elementary", "meal_type": "lunch", "period_label": label, "pdf_url": "https://x.test/HILL.pdf", "school_id": hill_id},
        ]

    async def parse(pdf_url, period_label, meal_type=None):
        return [{"date": datetime(2026, month, 15, tzinfo=_TZ), "description": "Hill pizza" if "HILL" in pdf_url else "Shared pasta", "notes": None}]

    monkeypatch.setattr(lunch_menu_scan, "discover_current_menus", discover)
    monkeypatch.setattr(lunch_menu_scan, "parse_menu_pdf", parse)

    async with database.SessionLocal() as db:
        assert (await lunch_menu_scan.run(db, {"district_id": district_id})).startswith("found 2 menu(s), 2 newly parsed")
        # A second scan finds both already stored.
        assert "0 newly parsed" in await lunch_menu_scan.run(db, {"district_id": district_id})
        assert seen["schools"] == ["Hill", "Shared"]

        menus = (await db.execute(select(LunchMenu).where((LunchMenu.district_id == district_id) | (LunchMenu.school_id == hill_id)))).scalars().all()
        assert sorted((m.district_id == district_id, m.school_id == hill_id, m.school_type) for m in menus) == [(False, True, None), (True, False, "elementary")]

        day = datetime(2026, month, 15, tzinfo=_TZ).date()
        shared_school = (await db.execute(select(School).where(School.slug == f"shared-{tag}"))).scalar_one()
        hill_school = await db.get(School, hill_id)
        own = await resolve_lunch_menu(db, hill_school, "lunch", on=day)
        other = await resolve_lunch_menu(db, shared_school, "lunch", on=day)
        assert own.school_id == hill_id and other.district_id == district_id
        assert (await db.execute(select(LunchMenuItem.description).where(LunchMenuItem.lunch_menu_id == own.id))).scalar_one() == "Hill pizza"
