import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import School, User


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"an_admin_{tag}@example.com"
    res = await client.post(
        "/auth/register", json={"email": email, "username": f"an_admin_{tag}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.anyio
async def test_repeat_views_increment_one_counter():
    # A source unique to this test. The counters are a shared, app-wide
    # table that legitimately contains real traffic (including whatever a
    # browser generated against the local stack), so asserting on a global
    # total is a test that fails for reasons that aren't bugs.
    source = f"src{uuid.uuid4().hex[:10]}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(3):
            res = await client.post("/page-views", json={"path": "/chcomms", "source": source})
            assert res.status_code == 204
        headers = await _admin_headers(client)
        report = (await client.get("/page-views", headers=headers)).json()

    assert report["totals_by_source"][source] == 3
    # One aggregate row, not one row per visit - the whole privacy premise.
    rows = [r for r in report["rows"] if r["path"] == "/chcomms" and r["source"] == source]
    assert len(rows) == 1
    assert rows[0]["count"] == 3


@pytest.mark.anyio
async def test_sources_are_counted_separately():
    # Unique per run for the same reason as above: totals_by_source sums
    # across every path, so a real visit recorded by a browser against the
    # local stack would otherwise count toward "direct" here.
    tag = uuid.uuid4().hex[:10]
    from_social, from_nowhere = f"social{tag}", f"none{tag}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/page-views", json={"path": "/survey", "source": from_social})
        await client.post("/page-views", json={"path": "/survey", "source": from_nowhere})
        headers = await _admin_headers(client)
        report = (await client.get("/page-views", headers=headers)).json()

    assert report["totals_by_source"][from_social] == 1
    assert report["totals_by_source"][from_nowhere] == 1


@pytest.mark.anyio
async def test_untracked_path_is_ignored_not_stored():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/page-views", json={"path": "/admin/secrets", "source": "facebook"})
        assert res.status_code == 204
        headers = await _admin_headers(client)
        report = (await client.get("/page-views", headers=headers)).json()
    assert "/admin/secrets" not in report["totals_by_path"]


@pytest.mark.anyio
async def test_school_page_counted_per_school_by_slug():
    tag = uuid.uuid4().hex[:10]
    async with database.SessionLocal() as db:
        school = School(name=f"Visit Test {tag}", slug=f"visit-test-{tag}")
        db.add(school)
        await db.commit()
        school_id = school.id
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # By slug and by id both land on the slug's row.
        await client.post("/page-views", json={"path": f"/schools/visit-test-{tag}", "source": "direct"})
        await client.post("/page-views", json={"path": f"/schools/{school_id}", "source": "direct"})
        await client.post("/page-views", json={"path": f"/schools/no-such-school-{tag}", "source": "direct"})
        await client.post("/page-views", json={"path": "/local", "source": "direct"})
        headers = await _admin_headers(client)
        report = (await client.get("/page-views", headers=headers)).json()

    assert report["totals_by_path"][f"/schools/visit-test-{tag}"] == 2
    assert f"/schools/{school_id}" not in report["totals_by_path"]
    assert f"/schools/no-such-school-{tag}" not in report["totals_by_path"]
    assert "/local" in report["totals_by_path"]


@pytest.mark.anyio
async def test_localz_pages_counted_without_the_listing():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for path in ("/localz", "/localz/", "/localz/food", "/localz/providers", "/localz/r/:id", "/localz/r/abc123", "/localz/no-such-category"):
            await client.post("/page-views", json={"path": path, "source": "direct"})
        headers = await _admin_headers(client)
        report = (await client.get("/page-views", headers=headers)).json()

    totals = report["totals_by_path"]
    assert totals["/localz"] >= 2 and "/localz/" not in totals
    assert totals["/localz/food"] >= 1 and totals["/localz/providers"] >= 1
    # Both listing forms land on one row; the listing id is never stored.
    assert totals["/localz/r/:id"] >= 2
    assert "/localz/r/abc123" not in totals
    assert "/localz/no-such-category" not in totals


@pytest.mark.anyio
async def test_junk_source_is_normalized():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/page-views", json={"path": "/chcomms", "source": "<script>alert(1)</script>"})
        headers = await _admin_headers(client)
        report = (await client.get("/page-views", headers=headers)).json()
    assert "other" in report["totals_by_source"]
    assert not any("script" in key for key in report["totals_by_source"])


@pytest.mark.anyio
async def test_report_requires_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/page-views")).status_code == 401
