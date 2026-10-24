import os
import uuid
from datetime import UTC, datetime

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
        "start_date": datetime(2026, 9, day, tzinfo=UTC),
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


@pytest.mark.anyio
async def test_school_feed_drops_district_events_copied_under_new_uids(monkeypatch):
    # Older Finalsite calendars (Lumberton) repeat the district's closures in a
    # school feed with fresh UIDs; the same day and title still marks a copy.
    copied = [_event("s-labor", "District  closed for Labor Day", 7), _event("s-picture", "Picture Day", 16)]

    async def fake_fetch(url: str) -> list[dict]:
        return [dict(e) for e in (copied if "school" in url else DISTRICT_FEED)]

    monkeypatch.setattr(district_calendar_scan, "fetch_district_calendar", fake_fetch)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Test District {tag}")
        db.add(district)
        await db.flush()
        school = School(name=f"Test School {tag}", slug=f"test-{tag}", district_id=district.id, school_type="elementary")
        db.add(school)
        await db.flush()
        district.ics_feeds = [
            {"name": "District", "url": "https://x/district.ics"},
            {"name": "BRS", "url": "https://x/school.ics", "school_slug": school.slug},
        ]
        await db.commit()

        await district_calendar_scan.run(db, {"district_id": district.id})
        await db.flush()

        school_rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
        assert [r.title for r in school_rows] == ["Picture Day"]


@pytest.mark.anyio
async def test_apptegy_feed_uses_org_id_not_url(monkeypatch):
    """Collingswood/Oaklyn/Woodlynne run Apptegy, not Finalsite - a feed
    entry with platform="apptegy" goes through services/apptegy.py instead
    of the .ics fetcher, keyed on org_id rather than url."""
    seen_org_ids = []

    async def fake_apptegy_fetch(org_id, start, end):
        seen_org_ids.append(org_id)
        return [_event("u-apptegy", "Staff PD", 5)]

    async def fail_if_called(url):
        raise AssertionError("ics fetcher should not be called for an apptegy feed")

    monkeypatch.setattr(district_calendar_scan, "fetch_apptegy_events", fake_apptegy_fetch)
    monkeypatch.setattr(district_calendar_scan, "fetch_district_calendar", fail_if_called)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Test Apptegy District {tag}")
        db.add(district)
        await db.flush()
        district.ics_feeds = [{"name": "District", "platform": "apptegy", "org_id": "4848"}]
        await db.commit()

        result = await district_calendar_scan.run(db, {"district_id": district.id})
        await db.flush()

        assert seen_org_ids == ["4848"]
        rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.district_id == district.id))).scalars().all()
        assert [r.title for r in rows] == ["Staff PD"]
        assert "1 new" in result


def _upcoming(uid: str, title: str, day: int) -> dict:
    return {**_event(uid, title, day), "start_date": datetime(2027, 3, day, tzinfo=UTC)}


@pytest.mark.anyio
async def test_an_event_gone_from_the_feed_is_retired_but_a_failed_fetch_retires_nothing(monkeypatch):
    closure, fair, past = _upcoming("u-closed", "SCHOOLS CLOSED", 3), _upcoming("u-fair", "Book Fair", 10), _event("u-old", "Old Event", 2)
    feed = {"events": [closure, fair, past]}

    async def fake_fetch(url: str) -> list[dict]:
        return [dict(e) for e in feed["events"]]

    monkeypatch.setattr(district_calendar_scan, "fetch_district_calendar", fake_fetch)
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Retire District {tag}", ics_feeds=[{"name": "District", "url": "https://x/d.ics"}])
        db.add(district)
        await db.commit()

        async def current() -> set[str]:
            await db.flush()
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.district_id == district.id))).scalars().all()
            return {r.title for r in rows if r.is_current}

        await district_calendar_scan.run(db, {"district_id": district.id})
        assert await current() == {"SCHOOLS CLOSED", "Book Fair", "Old Event"}

        # The district deleted its mistaken closure (and the past event aged
        # off the feed): only the upcoming one is retired.
        feed["events"] = [fair]
        note = await district_calendar_scan.run(db, {"district_id": district.id})
        assert await current() == {"Book Fair", "Old Event"} and "1 no longer on the feed" in note

        # A fetch that failed returns [] - never "everything's gone".
        feed["events"] = []
        await district_calendar_scan.run(db, {"district_id": district.id})
        assert await current() == {"Book Fair", "Old Event"}

        # Back on the feed, current again.
        feed["events"] = [closure, fair]
        await district_calendar_scan.run(db, {"district_id": district.id})
        assert await current() == {"SCHOOLS CLOSED", "Book Fair", "Old Event"}
