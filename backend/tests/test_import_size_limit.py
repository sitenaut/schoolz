"""An import too big to hold in memory is refused before it is read
(import_size_limit.py): a 183-page publish once took the API machine past
its memory and down for everyone."""
import json
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
import import_size_limit
from main import app
from models import User

FEED_URL = "https://classroom.google.com/u/2/w/AAAASLUG/t/all"
CAP = 2000


@pytest.fixture(autouse=True)
def _small_cap(monkeypatch):
    monkeypatch.setattr(import_size_limit, "IMPORT_MAX_BYTES", CAP)


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _envelope(text: str) -> dict:
    return {"adapter": "classroom", "source_url": FEED_URL, "reduced_text": text,
            "captured_at": "2026-09-14T13:00:00Z", "status": "ok", "char_count": len(text)}


async def _guardian_with_child(client: AsyncClient) -> tuple[str, str]:
    admin_email = f"cap_admin_{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post("/auth/register", json={"email": admin_email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"})
    admin = res.json()["access_token"]
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == admin_email).values(is_admin=True))
        await db.commit()
    school = await client.post("/schools", json={"name": f"Cap High {uuid.uuid4().hex[:6]}"}, headers=_auth(admin))
    res = await client.post("/auth/register", json={"email": f"cap_{uuid.uuid4().hex[:8]}@example.com", "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"})
    token = res.json()["access_token"]
    child = await client.post(
        "/students",
        json={"first_name": "Sample", "last_name": "Student", "student_id": "1234567", "school_id": school.json()["id"]},
        headers=_auth(token),
    )
    assert child.status_code == 201, child.text
    return token, child.json()["id"]


@pytest.mark.anyio
async def test_an_import_over_the_cap_is_refused_and_one_under_it_is_stored():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token, child = await _guardian_with_child(client)
        text = "[aria-label] Google Account: Sample Student\n(1234567@example.org) (role=button)\nNothing due"

        small = await client.post("/bucket3/import", json={"captures": [_envelope(text)]}, headers=_auth(token))
        assert small.status_code == 200, small.text

        big = {"captures": [_envelope(text + "\n" + "x" * CAP)]}
        for path in ("/bucket3/import", f"/students/{child}/bucket3/import"):
            res = await client.post(path, json=big, headers=_auth(token))
            assert res.status_code == 413
            assert res.json()["code"] == "too_large"
            assert "Update Backpack Capture" in res.json()["detail"]


@pytest.mark.anyio
async def test_the_refusal_comes_before_sign_in_is_checked_and_a_browser_can_read_it():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post(
            "/bucket3/import",
            content=json.dumps({"captures": [_envelope("x" * CAP)]}),
            headers={"Content-Type": "application/json", "Origin": "http://localhost:5173"},
        )
        assert res.status_code == 413
        assert res.headers["access-control-allow-origin"] == "http://localhost:5173"


@pytest.mark.anyio
async def test_a_body_with_no_declared_length_is_counted_as_it_arrives():
    async def chunks(total: int):
        for _ in range(total // 500):
            yield b"x" * 500

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        over = await client.post("/bucket3/import", content=chunks(CAP + 1000), headers={"Content-Type": "application/json"})
        assert over.status_code == 413

        # Under the cap it reaches the route, which wants a sign-in first.
        body = json.dumps({"captures": []}).encode()

        async def one():
            yield body

        under = await client.post("/bucket3/import", content=one(), headers={"Content-Type": "application/json"})
        assert under.status_code == 401


@pytest.mark.anyio
async def test_other_routes_are_not_capped():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.post("/capture-devices/diagnostics", content=json.dumps({"log": ["x" * CAP]}),
                                headers={"Content-Type": "application/json"})
        assert res.status_code == 401
