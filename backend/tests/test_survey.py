import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import District, School, User


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"survey_admin_{tag}@example.com"
    res = await client.post(
        "/auth/register", json={"email": email, "username": f"survey_admin_{tag}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _make_school() -> str:
    async with database.SessionLocal() as db:
        district = District(name=f"Survey District {uuid.uuid4().hex[:6]}")
        db.add(district)
        await db.flush()
        school = School(
            name=f"Survey Elementary {uuid.uuid4().hex[:6]}",
            slug=f"survey-elementary-{uuid.uuid4().hex[:6]}",
            school_type="elementary",
            district_id=district.id,
        )
        db.add(school)
        await db.commit()
        return school.id


@pytest.mark.anyio
async def test_anyone_can_submit_without_an_account():
    school_id = await _make_school()
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/survey",
            json={
                "school_ids": [school_id],
                "satisfaction": 2,
                "pain_points": ["absence", "pta"],
                "comments": "I never hear about form deadlines until they've passed.",
            },
        )
    assert res.status_code == 201, res.text
    body = res.json()
    assert body["satisfaction"] == 2
    assert body["pain_points"] == ["absence", "pta"]
    # Defaults to the privacy-preserving option when the form doesn't say.
    assert body["share_consent"] == "anonymous"


@pytest.mark.anyio
async def test_empty_submission_is_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/survey", json={"school_ids": [], "pain_points": []})
    assert res.status_code == 400


@pytest.mark.anyio
async def test_unknown_school_is_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/survey", json={"school_ids": ["nope"], "satisfaction": 3})
    assert res.status_code == 400


@pytest.mark.anyio
async def test_satisfaction_is_bounded():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/survey", json={"satisfaction": 9})
    assert res.status_code == 422


@pytest.mark.anyio
async def test_summary_is_public_and_hides_free_text():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        await client.post("/survey", json={"satisfaction": 4, "pain_points": ["lunch_menu"], "comments": "secret"})
        res = await client.get("/survey/summary")
    assert res.status_code == 200
    body = res.json()
    assert body["total"] >= 1
    assert "secret" not in res.text
    assert any(p["key"] == "lunch_menu" for p in body["top_pain_points"])


@pytest.mark.anyio
async def test_responses_require_admin():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        assert (await client.get("/survey/responses")).status_code == 401
        assert (await client.get("/survey/responses.csv")).status_code == 401

        headers = await _admin_headers(client)
        await client.post("/survey", json={"satisfaction": 1, "comments": "the bus thing"})
        listed = await client.get("/survey/responses", headers=headers)
        assert listed.status_code == 200
        assert any(r["comments"] == "the bus thing" for r in listed.json())

        csv_res = await client.get("/survey/responses.csv", headers=headers)
    assert csv_res.status_code == 200
    assert csv_res.headers["content-type"].startswith("text/csv")
    assert "submitted_at_utc" in csv_res.text
    assert "the bus thing" in csv_res.text


@pytest.mark.anyio
async def test_raw_ip_is_never_stored():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/survey",
            json={"satisfaction": 5},
            headers={"fly-client-ip": "203.0.113.42", "user-agent": "pytest-ua"},
        )
        assert res.status_code == 201
        headers = await _admin_headers(client)
        csv_res = await client.get("/survey/responses.csv", headers=headers)
    assert "203.0.113.42" not in csv_res.text
