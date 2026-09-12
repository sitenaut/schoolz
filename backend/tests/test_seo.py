import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import District, School


_WEB_URL = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")


@pytest.mark.anyio
async def test_sitemap_lists_static_routes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    for path in ("/", "/schools", "/calendar", "/lunch", "/privacy", "/contact"):
        assert f"<loc>{_WEB_URL}{path}</loc>" in res.text


@pytest.mark.anyio
async def test_sitemap_includes_school_slugs():
    async with database.SessionLocal() as db:
        district = District(name="Test District")
        db.add(district)
        await db.flush()
        db.add(School(name="Test Elementary", slug="test-elementary", school_type="elementary", district_id=district.id))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert f"<loc>{_WEB_URL}/schools/test-elementary</loc>" in res.text


@pytest.mark.anyio
async def test_prerender_rejects_unlisted_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/prerender", params={"path": "/admin"})
    assert res.status_code == 404
