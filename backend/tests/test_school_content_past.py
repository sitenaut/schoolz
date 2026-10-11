import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import School, SchoolContentItem


@pytest.mark.anyio
async def test_content_hides_past_dated_items_unless_asked():
    run = uuid.uuid4().hex[:8]
    now = datetime.now(timezone.utc)
    async with database.SessionLocal() as db:
        school = School(name=f"Past School {run}", slug=f"past-{run}", school_type="elementary")
        db.add(school)
        await db.flush()
        for title, cat, start, end in [
            ("Old", "event", now - timedelta(days=30), None),
            ("Old span still running", "event", now - timedelta(days=3), now + timedelta(days=2)),
            ("Soon", "event", now + timedelta(days=5), None),
            ("Undated", "program", None, None),
        ]:
            db.add(SchoolContentItem(scope="school", school_id=school.id, category=cat, title=title,
                                     start_date=start, end_date=end, is_current=True))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        default = {i["title"] for i in (await client.get(f"/schools/{school.slug}/content")).json()}
        full = {i["title"] for i in (await client.get(f"/schools/{school.slug}/content", params={"include_past": "true"})).json()}
    assert default == {"Old span still running", "Soon", "Undated"}
    assert full == default | {"Old"}
