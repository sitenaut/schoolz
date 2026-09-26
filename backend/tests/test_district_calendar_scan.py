import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from sqlalchemy import select

import database
from models import District, School, SchoolContentItem
from scheduler.jobs import district_calendar_scan


def _event(uid: str, title: str, day: int) -> dict:
    return {
        "external_uid": uid,
        "title": title,
        "description": None,
        "start_date": datetime(2026, 9, day, tzinfo=timezone.utc),
        "end_date": None,
        "is_all_day": True,
    }


DISTRICT_FEED = [_event("u-labor", "District Closed for Labor Day", 7), _event("u-first", "First Day of School", 3)]
# A Finalsite per-school feed repeats the district's events under the same UIDs.
SCHOOL_FEED = DISTRICT_FEED + [_event("u-picture", "Picture Day", 16), _event("u-day1", "Day 1", 2)]


@pytest.mark.anyio
async def test_school_feed_keeps_only_its_own_events_scoped_to_the_school(monkeypatch):
    async def fake_fetch(url: str) -> list[dict]:
        return [dict(e) for e in (SCHOOL_FEED if "school" in url else DISTRICT_FEED)]

    monkeypatch.setattr(district_calendar_scan, "fetch_district_calendar", fake_fetch)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Test District {tag}")
        db.add(district)
        await db.flush()
        school = School(name=f"Test School {tag}", slug=f"test-{tag}", district_id=district.id, school_type="middle")
        db.add(school)
        await db.flush()
        district.ics_feeds = [
            {"name": "District", "url": "https://x/district.ics"},
            {"name": "VMS", "url": "https://x/school.ics", "school_slug": school.slug},
        ]
        await db.commit()

        await district_calendar_scan.run(db, {"district_id": district.id})
        await db.flush()

        district_rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.district_id == district.id))).scalars().all()
        school_rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()

        assert sorted(r.title for r in district_rows) == ["District Closed for Labor Day", "First Day of School"]
        assert sorted(r.title for r in school_rows) == ["Day 1", "Picture Day"]
        assert all(r.scope == "school" and r.district_id is None for r in school_rows)

        # A re-scan updates in place rather than duplicating either set.
        await district_calendar_scan.run(db, {"district_id": district.id})
        await db.flush()
        again = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
        assert len(again) == 2
