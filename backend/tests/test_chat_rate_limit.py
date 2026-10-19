"""The chat's per-connection limit lives in the database (routers/chat.py), so
every API machine shares one count and a deploy doesn't reset it."""
from datetime import UTC, datetime, timedelta

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

import database
from main import app
from models import ChatRateWindow
from routers import chat as chat_router

pytestmark = pytest.mark.anyio


@pytest.fixture
def fake_turn(monkeypatch):
    async def turn(*args, **kwargs):
        return {"reply": "ok", "model": None, "history": [], "escalated": False}

    monkeypatch.setattr(chat_router, "run_chat_turn", turn)
    monkeypatch.setattr(chat_router, "_MAX_MESSAGES_PER_WINDOW", 3)


async def _send(ip):
    # Off Fly, client_ip() is the socket peer.
    async with AsyncClient(transport=ASGITransport(app=app, client=(ip, 50000)), base_url="http://test") as client:
        return await client.post("/chat", json={"message": "hi"})


async def test_the_limit_refuses_after_the_cap_and_only_that_connection(fake_turn):
    codes = [(await _send("203.0.113.7")).status_code for _ in range(4)]
    other = (await _send("203.0.113.8")).status_code
    assert codes == [200, 200, 200, 429]
    assert other == 200


async def test_only_a_hash_of_the_address_is_stored(fake_turn):
    await _send("203.0.113.9")
    async with database.SessionLocal() as db:
        hashes = (await db.execute(select(ChatRateWindow.ip_hash))).scalars().all()
    assert chat_router._ip_hash("203.0.113.9") in hashes
    assert not any("203.0.113.9" in h for h in hashes)


async def test_a_new_window_clears_day_old_rows(fake_turn):
    old = datetime.now(UTC) - timedelta(days=2)
    async with database.SessionLocal() as db:
        db.add(ChatRateWindow(ip_hash="x" * 64, window_start=old, count=5))
        await db.commit()
    await _send("203.0.113.10")
    async with database.SessionLocal() as db:
        left = (await db.execute(select(func.count()).where(ChatRateWindow.window_start < old + timedelta(hours=1)))).scalar_one()
    assert left == 0
