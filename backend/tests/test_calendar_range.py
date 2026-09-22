import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime, timezone

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import District, School, SchoolContentItem


def _utc(*args):
    return datetime(*args, tzinfo=timezone.utc)


@pytest.mark.anyio
async def test_month_range_excludes_all_day_item_ending_at_the_month_start():
    async with database.SessionLocal() as db:
        district = District(name="Range Test District")
        db.add(district)
        await db.flush()
        school = School(name="Range Test High", slug="range-test-high", school_type="high", district_id=district.id)
        db.add(school)
        await db.flush()
        common = dict(scope="district", district_id=district.id, category="event", is_current=True, source="ics_feed")
        db.add_all(
            [
                # Aug 31 only: ICS-style exclusive end at Sep 1 00:00 ET.
                SchoolContentItem(title="RANGE Aug 31 in-service", start_date=_utc(2026, 8, 31, 4), end_date=_utc(2026, 9, 1, 4), is_all_day=True, **common),
                # Aug 31 - Sep 1: genuinely reaches into September.
                SchoolContentItem(title="RANGE two-day", start_date=_utc(2026, 8, 31, 4), end_date=_utc(2026, 9, 2, 4), is_all_day=True, **common),
                # Timed event ending exactly at the range start still touches it.
                SchoolContentItem(title="RANGE timed overnight", start_date=_utc(2026, 9, 1, 2), end_date=_utc(2026, 9, 1, 4), is_all_day=False, **common),
                SchoolContentItem(title="RANGE Sep 1", start_date=_utc(2026, 9, 1, 4), is_all_day=True, **common),
            ]
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get(
            "/calendar",
            params={"start": "2026-09-01T04:00:00Z", "end": "2026-10-01T03:59:59Z", "school_ids": "range-test-high", "q": "RANGE"},
        )
    assert res.status_code == 200, res.text
    titles = {i["title"] for i in res.json()}
    assert titles == {"RANGE two-day", "RANGE timed overnight", "RANGE Sep 1"}
