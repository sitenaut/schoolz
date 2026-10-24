"""A marking-period date the district page stops listing (corrected, or
replaced by next year's) and the Kids View's cross-check against Genesis."""
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import pytest
from sqlalchemy import select

import database
from models import District, SchoolContentItem
from scheduler.jobs import marking_period_scan
from services import kids_view as kv

ET = ZoneInfo("America/New_York")


def _entry(tier: str, day) -> dict:
    return {
        "school_type": tier,
        "title": "Marking Period 1 Ends",
        "start_date": datetime.combine(day, datetime.min.time(), ET),
        "external_uid": f"marking_period:{tier}:Marking Period 1 Ends:{day.isoformat()}",
    }


@pytest.mark.anyio
async def test_a_date_the_page_moved_stops_showing_and_an_unread_tier_keeps_its_own(monkeypatch):
    soon = datetime.now(ET).date() + timedelta(days=20)
    reads = [
        [_entry("high", soon), _entry("middle", soon)],
        # The page moves the high school's date a day; the middle school's
        # table no longer parses.
        [_entry("high", soon + timedelta(days=1))],
    ]

    async def fake_fetch(url):
        return reads.pop(0)

    monkeypatch.setattr(marking_period_scan, "fetch_marking_period_page", fake_fetch)
    async with database.SessionLocal() as db:
        district = District(name=f"Marking Period District {uuid.uuid4().hex[:8]}", marking_period_url="https://x/mp")
        db.add(district)
        await db.commit()
        for _ in range(2):
            await marking_period_scan.run(db, {"district_id": district.id})
            await db.flush()
        rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.district_id == district.id))).scalars().all()
    current = sorted((r.applies_to_school_types[0], r.start_date.astimezone(ET).date()) for r in rows if r.is_current)
    assert current == [("high", soon + timedelta(days=1)), ("middle", soon)]


def test_genesis_periods_pair_with_the_nearest_district_date_in_their_school_year():
    genesis = {"MP1": "2026-11-06", "MP2": "2027-01-29", "MP3": "2027-04-09", "MP4": "2027-06-18"}
    # No MP1 on the district page, MP2's old date still stored beside the
    # corrected one, and next year's MP1 already posted: nothing disagrees.
    district = ["2027-01-27", "2027-01-29", "2027-04-09", "2027-06-18", "2027-11-05"]
    assert kv.marking_period_mismatches(genesis, district) == []
    assert kv.marking_period_mismatches(genesis, ["2027-01-27", "2027-04-09"]) == [("MP2", "2027-01-29", "2027-01-27")]
