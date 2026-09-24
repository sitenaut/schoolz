import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from main import app
from models import School, SchoolContentItem
from services.school_events_doc import SOURCE, parse_events_doc, scan_events_doc

FIXTURE = Path(__file__).parent / "fixtures" / "west_calendar_doc_2026_27.txt"
ET = ZoneInfo("America/New_York")


def _by_title(events):
    out = {}
    for e in events:
        out.setdefault(e["title"], []).append(e)
    return out


def test_parse_real_west_calendar_doc():
    events, stats = parse_events_doc(FIXTURE.read_text(encoding="utf-8"))
    by = _by_title(events)
    assert stats["unparsed"] == []
    assert len(events) == 61

    # Year comes from the doc's own "2026-27" title: fall -> 2026, spring -> 2027.
    assert by["Back to School Night"][0]["start_date"] == datetime(2026, 9, 10, 19, 0, tzinfo=ET)
    assert by["Graduation"][0]["start_date"] == datetime(2027, 6, 17, 16, 0, tzinfo=ET)
    assert by["Graduation"][0]["is_all_day"] is False
    # Multi-day all-day spans use the exclusive ICS end date.
    fall_play = by["Fall Play"][0]
    assert fall_play["is_all_day"] and fall_play["end_date"] == datetime(2026, 10, 5, 0, 0, tzinfo=ET)
    # "Oct. 12, 14, 15" -> three separate days; "Mar. 12-14, 19-21" -> two ranges.
    assert [e["start_date"].day for e in by["Senior Portrait Makeups"]] == [12, 14, 15]
    assert [(e["start_date"].day, e["end_date"].day) for e in by["Spring Musical"]] == [(12, 15), (19, 22)]
    # A timed range is one event per night, not a multi-day timed span.
    assert [e["start_date"] for e in by["Pop Concert"]] == [datetime(2027, 2, 17, 19, tzinfo=ET), datetime(2027, 2, 18, 19, tzinfo=ET)]
    # "Apr.20" (no space) and "Jan. 6." (trailing dot) forms both parse.
    assert by["World Language Cook Off"][0]["start_date"].date().isoformat() == "2027-04-20"
    # A time range stays in the title of an all-day row rather than being half-read.
    assert "New Student Orientation (9-11:30am)" in by
    # Closures, breaks and first/last day belong to the district calendar.
    assert not any("CLOSED" in t or "Break" in t or "Day of School" in t for t in by)
    assert stats["skipped_district_owned"] == 14
    # "Dec. - FAFSA (7pm)" has no day: skipped, never guessed.
    assert "FAFSA" not in by and stats["skipped_undated"] == 7


def test_unparseable_date_is_reported_not_dropped_silently():
    events, stats = parse_events_doc("Calendar 2026-27\nOct. 40- Impossible\nOct. 3- Real Thing\n")
    assert [e["title"] for e in events] == ["Real Thing"]
    assert stats["unparsed"] == ["Oct. 40- Impossible"]


@pytest.mark.anyio
async def test_scan_upserts_prunes_and_shows_on_school_page(monkeypatch):
    doc = {"text": "West Calendar 2026-27\n\tSept. 10- Back to School Night (7pm)\n\tOct. 9- Football Game (6pm)\n"}

    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, content=doc["text"].encode("utf-8"), request=httpx.Request("GET", url))

    # Scoped: the fake get() would otherwise also answer the test client below.
    with monkeypatch.context() as m:
        m.setattr(httpx.AsyncClient, "get", fake_get)

        async with database.SessionLocal() as db:
            school = School(name="Events Doc High", slug="events-doc-high", school_type="high", events_doc_url="https://docs.google.com/document/d/abc/edit")
            db.add(school)
            await db.flush()
            result = await scan_events_doc(db, school)
            assert "2 created" in result
            await db.commit()
            school_id = school.id

        # The Football Game line disappears from the doc ("subject to change").
        doc["text"] = "West Calendar 2026-27\n\tSept. 10- Back to School Night (7pm)\n"
        async with database.SessionLocal() as db:
            school = (await db.execute(select(School).where(School.id == school_id))).scalar_one()
            result = await scan_events_doc(db, school)
            assert "0 created, 1 updated, 1 removed" in result
            await db.commit()
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school_id, SchoolContentItem.source == SOURCE))).scalars().all()
            assert [r.title for r in rows] == ["Back to School Night"]

    # Not a class-page source: visible on the school's own content by default.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/schools/events-doc-high/content")
    assert res.status_code == 200, res.text
    assert [i["title"] for i in res.json()] == ["Back to School Night"]


@pytest.mark.anyio
async def test_empty_parse_never_prunes(monkeypatch):
    async def fake_get(self, url, **kwargs):
        return httpx.Response(200, content=b"totally restructured doc", request=httpx.Request("GET", url))

    monkeypatch.setattr(httpx.AsyncClient, "get", fake_get)
    async with database.SessionLocal() as db:
        school = School(name="Empty Doc High", slug="empty-doc-high", events_doc_url="https://docs.google.com/document/d/x/edit")
        db.add(school)
        await db.flush()
        db.add(SchoolContentItem(scope="school", school_id=school.id, source=SOURCE, external_uid="events_doc:keep", category="event", title="Keep me", is_current=True))
        await db.flush()
        result = await scan_events_doc(db, school)
        assert result.startswith("WARNING[no_events]")
        rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
        assert [r.title for r in rows] == ["Keep me"]
