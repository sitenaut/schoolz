"""Audit log (services/audit.py): routes in AUDITED are recorded whatever the
outcome, notes ride on their request, the table refuses UPDATE and DELETE,
and only super admins can read it."""
import uuid

import pytest
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, text, update
from sqlalchemy.exc import DBAPIError

import database
from main import app
from models import AuditEvent, User
from services import audit

pytestmark = pytest.mark.anyio


def _client():
    return AsyncClient(transport=ASGITransport(app=app, client=("198.51.100.4", 50000)), base_url="http://test")


async def _register(client, prefix, *, super_admin=False):
    run_id = uuid.uuid4().hex[:8]
    email = f"{prefix}_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"{prefix}_{run_id}", "password": "password123"})
    assert reg.status_code == 201, reg.text
    headers = {"authorization": f"Bearer {reg.json()['access_token']}"}
    me = (await client.get("/auth/me", headers=headers)).json()
    if super_admin:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
    return headers, me["id"]


async def _events(action):
    async with database.SessionLocal() as db:
        return list((await db.execute(select(AuditEvent).where(AuditEvent.action == action).order_by(AuditEvent.id))).scalars())


def test_every_audited_route_exists():
    routes = {
        (m, c.path) for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute) for m in c.methods
    }
    missing = [key for key in audit.AUDITED if key not in routes]
    assert not missing, f"AUDITED names routes that don't exist: {missing}"


async def test_a_role_change_is_recorded_with_actor_and_target():
    async with _client() as client:
        boss, boss_id = await _register(client, "audboss", super_admin=True)
        res = await client.post("/admin/roles", headers=boss, json={"name": f"Aud {uuid.uuid4().hex[:6]}", "permissions": []})
        assert res.status_code == 201
        role_id = res.json()["id"]
        assert (await client.delete(f"/admin/roles/{role_id}", headers=boss)).status_code == 204

    created, deleted = (await _events("role.create"))[-1], (await _events("role.delete"))[-1]
    assert (created.outcome, created.status, created.actor_user_id, created.credential) == ("success", 201, boss_id, "session")
    assert deleted.target == {"role_id": role_id}
    assert deleted.route == "/admin/roles/{role_id}" and deleted.method == "DELETE"
    assert deleted.request_id
    # A hash of the address, never the address.
    assert deleted.ip_hash == audit.ip_hash("198.51.100.4")


async def test_a_refused_call_is_recorded_as_denied():
    async with _client() as client:
        helper, helper_id = await _register(client, "audhelper")
        assert (await client.post("/admin/roles", headers=helper, json={"name": "x", "permissions": []})).status_code == 403
    event = (await _events("role.create"))[-1]
    assert (event.outcome, event.actor_user_id) == ("denied", helper_id)


async def test_an_invite_token_is_never_stored():
    async with _client() as client:
        headers, _ = await _register(client, "audinvite")
        await client.post("/invites/not-a-real-token/accept", headers=headers)
    event = (await _events("guardian.invite_accept"))[-1]
    assert event.outcome == "failed"
    assert "not-a-real-token" not in str(event.target)


async def test_unaudited_routes_write_nothing():
    async with database.SessionLocal() as db:
        before = (await db.execute(text("SELECT count(*) FROM audit_events"))).scalar_one()
    async with _client() as client:
        await client.get("/health")
        await client.get("/schools")
    async with database.SessionLocal() as db:
        assert (await db.execute(text("SELECT count(*) FROM audit_events"))).scalar_one() == before


async def test_a_note_is_written_with_its_request():
    from fastapi import Request

    @app.post("/_test_audit_note")
    async def noting(request: Request):
        audit.note(request, "test.note", thing="x", token="secret-value")
        return {}

    try:
        async with _client() as client:
            assert (await client.post("/_test_audit_note")).status_code == 200
    finally:
        app.router.routes = [r for r in app.router.routes if getattr(r, "path", None) != "/_test_audit_note"]
    event = (await _events("test.note"))[-1]
    assert event.outcome == "success" and event.target == {"thing": "x"}


async def test_the_table_refuses_update_and_delete():
    async with database.SessionLocal() as db:
        db.add(AuditEvent(action="test.append_only", outcome="success"))
        await db.commit()
    for statement in ("UPDATE audit_events SET outcome = 'failed' WHERE action = 'test.append_only'",
                      "DELETE FROM audit_events WHERE action = 'test.append_only'"):
        async with database.SessionLocal() as db:
            with pytest.raises(DBAPIError, match="append-only"):
                async with db.begin_nested():
                    await db.execute(text(statement))


async def test_only_super_admins_read_the_log():
    async with _client() as client:
        boss, _ = await _register(client, "audreader", super_admin=True)
        helper, _ = await _register(client, "audnobody")
        await client.post("/admin/roles", headers=boss, json={"name": f"Aud {uuid.uuid4().hex[:6]}", "permissions": []})
        assert (await client.get("/admin/audit-log", headers=helper)).status_code == 403
        page = await client.get("/admin/audit-log", headers=boss, params={"action": "role.", "limit": 1})
    assert page.status_code == 200
    body = page.json()
    assert body["events"][0]["action"] == "role.create"
    assert body["events"][0]["actor"].startswith("audreader_")
    assert "ip_hash" not in body["events"][0]


async def test_a_supabase_session_is_recorded_once_and_mfa_when_it_arrives(monkeypatch):
    import auth

    monkeypatch.setattr(auth, "AUTH_MODE", "supabase")
    monkeypatch.setattr(audit, "_seen_sessions", audit.OrderedDict())
    sub = f"sb-{uuid.uuid4().hex[:8]}"
    session_id = str(uuid.uuid4())

    async def verify(token):
        return {"sub": sub, "email": f"{sub}@example.com", "session_id": session_id, "aal": token}

    monkeypatch.setattr(auth, "_verify_supabase_token", verify)
    async with _client() as client:
        for aal in ("aal1", "aal1", "aal2", "aal2"):
            assert (await client.get("/auth/me", headers={"authorization": f"Bearer {aal}"})).status_code == 200
        # A restart forgets what this process saw; the table still knows.
        audit._seen_sessions.clear()
        assert (await client.get("/auth/me", headers={"authorization": "Bearer aal2"})).status_code == 200

    sign_ins = [e for e in await _events("auth.sign_in") if e.target.get("session_id") == session_id]
    mfa = [e for e in await _events("auth.mfa_passed") if e.target.get("session_id") == session_id]
    assert len(sign_ins) == 1 and len(mfa) == 1
    assert sign_ins[0].actor_user_id and sign_ins[0].credential == "session"
