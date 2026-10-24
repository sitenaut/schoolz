"""Bug sweep 2026-10-23 privacy fixes: invite tokens, invites that outlive
their inviter, a child's email, another child's pages, and chat history."""
import logging
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select

import database
from main import app
from models import Bucket3Capture, Bucket3SyncState
from routers import chat as chat_router
from tests.test_kids_api import _env, _family, _import, _load
from tests.test_students import _make_admin, _register, _unique

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _guardian_with_child(client: AsyncClient) -> tuple[dict, str, str]:
    run = uuid.uuid4().hex[:8]
    email = f"priv_{run}@example.com"
    headers = {"Authorization": f"Bearer {await _register(client, email, _unique('priv'))}"}
    await _make_admin(email)
    school = (await client.post("/schools", json={"name": f"Privacy School {run}"}, headers=headers)).json()
    student = await client.post(
        "/students",
        json={"first_name": "Nora", "last_name": "Lee", "student_id": f"p-{run}", "school_id": school["id"]},
        headers=headers,
    )
    return headers, student.json()["id"], run


async def _invite(client: AsyncClient, headers: dict, student_id: str) -> str:
    res = await client.post(f"/students/{student_id}/invites", json={"invitee_email": f"coparent_{uuid.uuid4().hex[:8]}@example.com"}, headers=headers)
    assert res.status_code == 201, res.text
    return res.json()["token"]


async def test_an_invite_token_never_reaches_the_request_log(caplog):
    async with _client() as client:
        headers, student_id, _ = await _guardian_with_child(client)
        token = await _invite(client, headers, student_id)
        with caplog.at_level(logging.INFO, logger="main"):
            assert (await client.get(f"/invites/{token}")).status_code == 200
    lines = [r for r in caplog.records if r.getMessage() == "http_request" and getattr(r, "route", None) == "/invites/{token}"]
    assert lines and all(token not in r.path for r in lines) and lines[0].path == "/invites/:token"


async def test_removing_the_child_withdraws_the_guardians_invites():
    async with _client() as client:
        headers, student_id, _ = await _guardian_with_child(client)
        token = await _invite(client, headers, student_id)
        assert (await client.delete(f"/students/{student_id}", headers=headers)).status_code in (200, 204)
        assert (await client.get(f"/invites/{token}")).json()["status"] == "revoked"
        stranger = {"Authorization": f"Bearer {await _register(client, f'x_{uuid.uuid4().hex[:8]}@example.com', _unique('x'))}"}
        assert (await client.post(f"/invites/{token}/accept", headers=stranger)).status_code == 410
        assert (await client.get("/students", headers=stranger)).json() == []


async def test_opening_your_own_invite_does_not_use_it_up():
    async with _client() as client:
        headers, student_id, _ = await _guardian_with_child(client)
        token = await _invite(client, headers, student_id)
        own = await client.post(f"/invites/{token}/accept", headers=headers)
        assert own.status_code == 409
        assert (await client.get(f"/invites/{token}")).json()["status"] == "pending"
        coparent = {"Authorization": f"Bearer {await _register(client, f'co_{uuid.uuid4().hex[:8]}@example.com', _unique('co'))}"}
        assert (await client.post(f"/invites/{token}/accept", headers=coparent)).status_code == 200


async def test_a_student_invite_never_shows_the_childs_full_email():
    async with _client() as client:
        headers, student_id, run = await _guardian_with_child(client)
        child_email = f"nora.lee.{run}@students.example.org"
        made = await client.post(f"/students/{student_id}/account-invites", json={"invitee_email": child_email}, headers=headers)
        assert made.status_code in (200, 201), made.text
        token = made.json()["token"]
        other = {"Authorization": f"Bearer {await _register(client, f'o_{run}@example.com', _unique('o'))}"}
        refused = await client.post(f"/student-account-invites/{token}/accept", headers=other)
    assert refused.status_code == 403 and child_email not in refused.text and "students.example.org" in refused.text


async def test_another_childs_page_is_never_kept_or_counted_as_a_fresh_look():
    async with _client() as client:
        _run, guardian, sid = await _family(client)  # this child's id is the fixture's 1234567
        daily = _load("genesis_daily_view.txt").replace("9999999", "7654321")
        sibling = "https://parents.example.org/genesis/parents?tab1=studentdata&tab2=studentsummary&studentid=7654321"
        for _ in range(2):  # and again: still a mismatch, never "a duplicate"
            result = await _import(client, guardian, sid, [_env("genesis", sibling, daily)])
            assert len(result["identity_mismatches"]) == 1 and result["captures_skipped_duplicate"] == 0
    async with database.SessionLocal() as db:
        kept = await db.scalar(select(func.count()).select_from(Bucket3Capture).where(Bucket3Capture.student_id == sid))
        sync = await db.get(Bucket3SyncState, sid)
    assert kept == 0 and (sync is None or sync.genesis_seen_at is None)


async def test_a_lapsed_sign_in_never_sends_a_childs_conversation_anywhere(monkeypatch):
    called = []

    async def _no_turn(*args, **kwargs):
        called.append(True)
        raise AssertionError("no provider may see this history")

    monkeypatch.setattr(chat_router, "run_chat_turn", _no_turn)
    history = [
        {"role": "user", "content": "what is Nora missing?"},
        {"role": "assistant", "content": [{"type": "tool_use", "id": "t1", "name": "get_child_todo", "input": {}}]},
        {"role": "user", "content": [{"type": "tool_result", "tool_use_id": "t1", "content": "Algebra: Unit 3 Quiz"}]},
        {"role": "assistant", "content": [{"type": "text", "text": "Nora is missing the Unit 3 Quiz."}]},
    ]
    async with _client() as client:
        res = await client.post("/chat", json={"message": "and tomorrow?", "history": history})
    assert res.status_code == 200 and res.json()["history"] == [] and "sign-in has expired" in res.json()["reply"]
    assert called == []
