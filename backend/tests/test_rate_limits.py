"""Adding children is limited per account and per connection
(routers/students.py): an add that matches a child's name and student ID
links the account to that child with no approval, so a stranger who knows a
child's name must not be able to guess the ID at speed."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import RateWindow, User
from routers import students as students_router
from services import rate_limit

pytestmark = pytest.mark.anyio


def _client(ip: str) -> AsyncClient:
    # Off Fly, client_ip() is the socket peer.
    return AsyncClient(transport=ASGITransport(app=app, client=(ip, 50000)), base_url="http://test")


async def _register(client: AsyncClient) -> tuple[str, str]:
    email = f"limits_{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post(
        "/auth/register", json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    return email, res.json()["access_token"]


async def _school(client: AsyncClient) -> str:
    email, token = await _register(client)
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    res = await client.post("/schools", json={"name": f"Limits Elementary {uuid.uuid4().hex[:8]}"}, headers=_auth(token))
    return res.json()["id"]


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _add(client: AsyncClient, token: str, school_id: str, student_id: str):
    return await client.post(
        "/students",
        json={"first_name": "Sample", "last_name": "Child", "student_id": student_id, "school_id": school_id},
        headers=_auth(token),
    )


async def test_an_account_gets_a_days_worth_of_adds_then_429(monkeypatch):
    monkeypatch.setattr(students_router, "ADDS_PER_ACCOUNT_PER_DAY", 3)
    async with _client("203.0.113.21") as client:
        school_id = await _school(client)
        _email, guesser = await _register(client)
        codes = [(await _add(client, guesser, school_id, f"g-{uuid.uuid4().hex[:6]}")).status_code for _ in range(4)]
        assert codes == [201, 201, 201, 429]
        refused = await _add(client, guesser, school_id, "another-guess")
        assert refused.status_code == 429
        assert "try again tomorrow" in refused.json()["detail"]

        # Someone else on the same connection still gets their own adds.
        _email, neighbour = await _register(client)
        assert (await _add(client, neighbour, school_id, f"n-{uuid.uuid4().hex[:6]}")).status_code == 201


async def test_a_connection_is_limited_across_accounts(monkeypatch):
    monkeypatch.setattr(students_router, "ADDS_PER_CONNECTION_PER_DAY", 2)
    async with _client("203.0.113.22") as client:
        school_id = await _school(client)
        codes = []
        for _ in range(3):
            _email, token = await _register(client)
            codes.append((await _add(client, token, school_id, f"c-{uuid.uuid4().hex[:6]}")).status_code)
        assert codes == [201, 201, 429]
    async with _client("203.0.113.23") as elsewhere:
        _email, token = await _register(elsewhere)
        assert (await _add(elsewhere, token, school_id, f"e-{uuid.uuid4().hex[:6]}")).status_code == 201


async def test_a_refused_add_creates_and_links_nothing(monkeypatch):
    monkeypatch.setattr(students_router, "ADDS_PER_ACCOUNT_PER_DAY", 1)
    async with _client("203.0.113.24") as client:
        school_id = await _school(client)
        _email, token = await _register(client)
        assert (await _add(client, token, school_id, f"r-{uuid.uuid4().hex[:6]}")).status_code == 201
        assert (await _add(client, token, school_id, f"r-{uuid.uuid4().hex[:6]}")).status_code == 429
        assert len((await client.get("/students", headers=_auth(token))).json()) == 1


async def test_only_a_hash_of_the_connection_is_kept_and_ipv6_counts_by_its_64():
    async with _client("203.0.113.25") as client:
        school_id = await _school(client)
        _email, token = await _register(client)
        await _add(client, token, school_id, f"h-{uuid.uuid4().hex[:6]}")
    async with database.SessionLocal() as db:
        keys = (await db.execute(select(RateWindow.key).where(RateWindow.bucket == "students.add.connection"))).scalars().all()
    assert rate_limit.connection_key("203.0.113.25") in keys
    assert not any("203.0.113" in k for k in keys)

    assert rate_limit.connection_key("2001:db8:1:2::1") == rate_limit.connection_key("2001:db8:1:2:ffff::9")
    assert rate_limit.connection_key("2001:db8:1:2::1") != rate_limit.connection_key("2001:db8:1:3::1")
    assert rate_limit.connection_key("::ffff:203.0.113.25") == rate_limit.connection_key("203.0.113.25")
    assert rate_limit.connection_key(None) is None
