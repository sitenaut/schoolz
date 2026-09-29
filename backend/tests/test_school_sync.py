"""local_events/school_sync.py - a local_events source tagging a RawEvent
with school_slug also publishes it on that school's own public page."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from local_events.school_sync import SOURCE, group_by_school, sync_school_content
from local_events.sources.base import RawEvent
from main import app
from models import School, SchoolContentItem

UTC = timezone.utc


def _event(uid, title, school_slug, when=None):
    return RawEvent(
        source="ludus_test", source_event_id=uid, title=title,
        start_time=when or datetime(2026, 12, 1, 19, 0, tzinfo=UTC),
        url="https://example.com/tickets", school_slug=school_slug,
    )


@pytest.mark.anyio
async def test_dual_write_upserts_prunes_and_shows_on_school_page():
    async with database.SessionLocal() as db:
        school = School(name="Sync High", slug="sync-high", school_type="high")
        db.add(school)
        await db.flush()

        result = await sync_school_content(db, group_by_school([
            _event("ludus:1:1", "Fall Play", "sync-high"),
            _event("ludus:1:2", "Fall Play (Sat matinee)", "sync-high"),
        ]))
        await db.commit()
        assert result == {"created": 2, "updated": 0, "removed": 0, "unknown_slugs": []}
        school_id = school.id

    # A re-run where one performance vanished and one is unchanged.
    async with database.SessionLocal() as db:
        result = await sync_school_content(db, group_by_school([
            _event("ludus:1:1", "Fall Play", "sync-high"),
        ]))
        await db.commit()
        assert result == {"created": 0, "updated": 1, "removed": 1, "unknown_slugs": []}

        rows = (await db.execute(
            select(SchoolContentItem).where(SchoolContentItem.school_id == school_id, SchoolContentItem.source == SOURCE)
        )).scalars().all()
        assert [r.title for r in rows] == ["Fall Play"]
        assert rows[0].category == "event" and rows[0].scope == "school"
        assert rows[0].link_url == "https://example.com/tickets"

    # Public, no login needed - same as every other SchoolContentItem source.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/schools/sync-high/content")
    assert res.status_code == 200, res.text
    assert [i["title"] for i in res.json()] == ["Fall Play"]


@pytest.mark.anyio
async def test_unknown_school_slug_is_reported_not_fatal():
    async with database.SessionLocal() as db:
        result = await sync_school_content(db, {"no-such-school": [_event("x:1", "Ghost Show", "no-such-school")]})
        assert result == {"created": 0, "updated": 0, "removed": 0, "unknown_slugs": ["no-such-school"]}


@pytest.mark.anyio
async def test_two_schools_from_one_shared_source_stay_independent():
    async with database.SessionLocal() as db:
        chs = School(name="Shared CHS", slug="shared-chs", school_type="high")
        cms = School(name="Shared CMS", slug="shared-cms", school_type="middle")
        db.add_all([chs, cms])
        await db.flush()

        await sync_school_content(db, group_by_school([
            _event("ludus:1:1", "Comedy Night", "shared-chs"),
            _event("ludus:2:1", "Beauty and the Beast", "shared-cms"),
        ]))
        await db.commit()

        chs_rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == chs.id))).scalars().all()
        cms_rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == cms.id))).scalars().all()
        assert [r.title for r in chs_rows] == ["Comedy Night"]
        assert [r.title for r in cms_rows] == ["Beauty and the Beast"]
