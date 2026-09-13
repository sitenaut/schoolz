import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import User


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"campaign_admin_{tag}@example.com"
    res = await client.post(
        "/auth/register", json={"email": email, "username": f"campaign_admin_{tag}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.anyio
async def test_campaign_report_requires_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/page-views/campaign-report")
    assert res.status_code == 401


@pytest.mark.anyio
async def test_campaign_report_reflects_the_funnel():
    tag = uuid.uuid4().hex[:8]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        # Two chcomms reads from Facebook, one survey open, one completed
        # survey, one submitted (still-pending) newsletter link.
        await client.post("/page-views", json={"path": "/chcomms", "source": f"facebook{tag}"})
        await client.post("/page-views", json={"path": "/chcomms", "source": f"facebook{tag}"})
        await client.post("/page-views", json={"path": "/survey", "source": f"facebook{tag}"})
        await client.post("/survey", json={"satisfaction": 4})
        await client.post("/submissions", data={"url": f"https://app.smore.com/n/{tag}"})

        headers = await _admin_headers(client)
        res = await client.get("/page-views/campaign-report", headers=headers)

    assert res.status_code == 200
    body = res.json()
    assert body["chcomms_reads"] >= 2
    assert body["survey_opened"] >= 1
    assert body["survey_completed"] >= 1
    assert body["newsletters_submitted"] >= 1
    assert body["newsletters_pending"] >= 1
    assert body["by_source"].get(f"facebook{tag}") == 3
    assert body["total_visits"] >= 3
    # Every visit in this test happened today - the report's own "today"
    # bucket should account for it.
    assert body["visits_today"] >= 3
    assert isinstance(body["by_day"], list) and len(body["by_day"]) >= 1
