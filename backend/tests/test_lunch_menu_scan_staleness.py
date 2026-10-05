import os
import uuid
from datetime import date, datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest

import database
from models import District, School
from scheduler.jobs import lunch_menu_scan

_TZ = ZoneInfo("America/New_York")


async def _district() -> District:
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        d = District(name=f"District {tag}", food_services_menu_url="https://x.test/menus")
        db.add(d)
        await db.flush()
        db.add(School(name=f"High {tag}", slug=f"high-{tag}", district_id=d.id, school_type="high"))
        await db.commit()
        await db.refresh(d)
    return d


def _fake(monkeypatch, month: int, today: date):
    label = f"{lunch_menu_scan._MONTHS[month - 1]} 2026"
    url = f"https://x.test/{label.replace(' ', '')}.pdf"

    async def discover(page_url, school_types=None):
        return [{"school_type": "high", "meal_type": "lunch", "period_label": label, "pdf_url": url}]

    async def parse(pdf_url, period_label, meal_type=None):
        return [{"date": datetime(2026, month, 15, tzinfo=_TZ), "description": "Pizza", "notes": None}]

    monkeypatch.setattr(lunch_menu_scan, "discover_current_menus", discover)
    monkeypatch.setattr(lunch_menu_scan, "parse_menu_pdf", parse)
    monkeypatch.setattr(lunch_menu_scan, "_today", lambda: today)


@pytest.mark.anyio
async def test_last_months_menu_still_posted_is_a_warning(monkeypatch):
    d = await _district()
    _fake(monkeypatch, 9, date(2026, 10, 4))
    async with database.SessionLocal() as db:
        first = await lunch_menu_scan.run(db, {"district_id": d.id})
        assert first.startswith("WARNING[menu_out_of_date]:") and "isn't October's" in first
        # ...and it stays a warning on every later run, not just the first.
        again = await lunch_menu_scan.run(db, {"district_id": d.id})
        assert again.startswith("WARNING[menu_out_of_date]:") and "0 newly parsed" in again


@pytest.mark.anyio
async def test_current_month_menu_is_success(monkeypatch):
    d = await _district()
    _fake(monkeypatch, 10, date(2026, 10, 4))
    async with database.SessionLocal() as db:
        result = await lunch_menu_scan.run(db, {"district_id": d.id})
        assert result == "found 1 menu(s), 1 newly parsed"


@pytest.mark.anyio
async def test_no_warning_over_the_summer(monkeypatch):
    d = await _district()
    _fake(monkeypatch, 6, date(2026, 7, 20))
    async with database.SessionLocal() as db:
        result = await lunch_menu_scan.run(db, {"district_id": d.id})
        assert not result.startswith("WARNING")
