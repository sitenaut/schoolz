"""The chatbot's personal tools (services/chatbot_personal.py) and the
/chat endpoint's decision to offer them only to a signed-in caller."""
import json
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from routers import chat as chat_router
from services.chatbot_personal import PersonalTools
from tests.test_kids_api import _auth, _family, _register


@pytest.mark.anyio
async def test_personal_tools_see_only_the_callers_own_children():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        _run2, _other_guardian, other_sid = await _family(client, student_id="7654321", first_name="Other")

    tools = PersonalTools(app, guardian)
    try:
        children = json.loads(await tools.run("list_my_children", {}))
        assert [c["id"] for c in children["items"]] == [sid]

        todo = json.loads(await tools.run("get_child_todo", {"student_id": sid}))
        assert "missing" in todo and "error" not in todo

        # Another family's child is refused by the route's own ownership check.
        foreign = json.loads(await tools.run("get_child_todo", {"student_id": other_sid}))
        assert foreign["error"].startswith("404")

        # A model-built path fragment never reaches a URL.
        bad = json.loads(await tools.run("get_child_todo", {"student_id": "../notifications"}))
        assert "list_my_children" in bad["error"]
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_student_account_sees_itself():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, sid = await _family(client)
        kid_email = f"chatkid_{run}@example.com"
        invite = await client.post(
            f"/students/{sid}/account-invites", json={"invitee_email": kid_email}, headers=_auth(guardian)
        )
        kid = await _register(client, kid_email)
        accepted = await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(kid))
        assert accepted.status_code == 200, accepted.text

    tools = PersonalTools(app, kid)
    try:
        children = json.loads(await tools.run("list_my_children", {}))
        assert [c["id"] for c in children["items"]] == [sid]
        assert "error" not in json.loads(await tools.run("get_child_schedule", {"student_id": sid}))
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_chat_offers_personal_tools_only_when_signed_in(monkeypatch):
    seen = []

    async def fake_turn(mcp, history, message, already_escalated, personal=None):
        seen.append(personal)
        return {"reply": "ok", "model": None, "history": [], "escalated": False}

    monkeypatch.setattr(chat_router, "run_chat_turn", fake_turn)
    monkeypatch.setattr(chat_router, "_requests_by_ip", chat_router.defaultdict(chat_router.deque))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register(client, f"chat_{uuid.uuid4().hex[:8]}@example.com")
        assert (await client.post("/chat", json={"message": "hi"})).status_code == 200
        assert (await client.post("/chat", json={"message": "hi"}, headers=_auth("not-a-token"))).status_code == 200
        assert (await client.post("/chat", json={"message": "hi"}, headers=_auth(token))).status_code == 200

    assert seen[0] is None
    assert seen[1] is None  # a bad token degrades to public, never 401s
    assert isinstance(seen[2], PersonalTools)
