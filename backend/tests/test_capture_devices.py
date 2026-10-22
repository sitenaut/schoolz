"""Backpack Capture's "Connect to schoolz" (routers/capture_devices.py) and
the capture key it hands out (auth.CAPTURE_KEY_ROUTES)."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import AuditEvent, User

FEED_URL = "https://classroom.google.com/u/2/w/AAAASLUG/t/all"


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/auth/register", json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    return res.json()["access_token"]


async def _guardian_with_child(client: AsyncClient) -> tuple[str, str, str]:
    """An ordinary guardian (not an admin) with one child."""
    admin_email = f"connect_admin_{uuid.uuid4().hex[:8]}@example.com"
    admin = await _register(client, admin_email)
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == admin_email).values(is_admin=True))
        await db.commit()
    school = await client.post("/schools", json={"name": f"Connect High {uuid.uuid4().hex[:6]}"}, headers=_auth(admin))
    school_id = school.json()["id"]

    email = f"connect_{uuid.uuid4().hex[:8]}@example.com"
    token = await _register(client, email)
    child = await client.post(
        "/students",
        json={"first_name": "Sample", "last_name": "Student", "student_id": "1234567", "school_id": school_id},
        headers=_auth(token),
    )
    assert child.status_code == 201, child.text
    return email, token, child.json()["id"]


async def _connect(client: AsyncClient, approver: str) -> dict:
    started = (await client.post("/capture-devices/start", json={"client_name": "Backpack Capture on Windows"})).json()
    assert started["connect_path"] == "/connect" and len(started["user_code"]) == 9
    pending = await client.post("/capture-devices/token", json={"device_code": started["device_code"]})
    assert pending.json() == {"status": "pending", "key": None, "device_id": None, "email": None}
    approved = await client.post(f"/capture-devices/requests/{started['user_code']}/approve", headers=_auth(approver))
    assert approved.json()["status"] == "approved", approved.text
    issued = (await client.post("/capture-devices/token", json={"device_code": started["device_code"]})).json()
    assert issued["status"] == "approved" and issued["key"].startswith("szc_")
    # Collected once; the device code is spent.
    again = await client.post("/capture-devices/token", json={"device_code": started["device_code"]})
    assert again.json()["status"] == "expired"
    return issued


@pytest.mark.anyio
async def test_connect_hands_out_a_key_that_only_sends_pages():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, guardian, child = await _guardian_with_child(client)
        issued = await _connect(client, guardian)
        assert issued["email"] == email
        key = _auth(issued["key"])

        # What the extension does with it...
        [kid] = (await client.get("/students", headers=key)).json()
        assert kid["id"] == child
        text = "[aria-label] Google Account: Sample Student\n(1234567@example.org) (role=button)\nNothing due"
        envelope = {"adapter": "classroom", "source_url": FEED_URL, "reduced_text": text,
                    "captured_at": "2026-09-14T13:00:00Z", "status": "ok", "char_count": len(text)}
        imported = await client.post("/bucket3/import", json={"captures": [envelope]}, headers=key)
        assert imported.status_code == 200 and imported.json()["students"][0]["student"] == child
        status = await client.post(f"/students/{child}/bucket3/capture-status", json={"status": "ok"}, headers=key)
        assert status.status_code == 200

        # ...and nothing else, not even reading what it sent.
        for method, path in [
            ("GET", "/auth/me"),
            ("GET", f"/students/{child}/bucket3/todo"),
            ("GET", f"/students/{child}/bucket3/status"),
            ("POST", f"/students/{child}/bucket3/reprocess"),
            ("GET", "/capture-devices"),
            ("DELETE", f"/students/{child}"),
            ("GET", "/admin/audit-log"),
        ]:
            res = await client.request(method, path, headers=key)
            assert res.status_code == 403, (method, path, res.status_code)

        # The person sees it under Account, and removing it cuts it off.
        [device] = (await client.get("/capture-devices", headers=_auth(guardian))).json()
        assert device["id"] == issued["device_id"] and device["name"] == "Backpack Capture on Windows"
        assert device["last_used_at"] is not None
        assert (await client.delete(f"/capture-devices/{device['id']}", headers=_auth(guardian))).status_code == 204
        assert (await client.get("/students", headers=key)).status_code == 401

        async with database.SessionLocal() as db:
            actions = set((await db.execute(select(AuditEvent.action))).scalars())
        assert {"capture_device.approve", "capture_device.issued", "capture_device.revoke"} <= actions


@pytest.mark.anyio
async def test_extension_sign_out_removes_its_own_key_and_nobody_elses():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, guardian, _child = await _guardian_with_child(client)
        mine = await _connect(client, guardian)
        other = await _connect(client, guardian)

        # A browser session can't use the extension's sign-out...
        assert (await client.post("/capture-devices/self/revoke", headers=_auth(guardian))).status_code == 400
        # ...and a stranger can't remove someone else's computer.
        stranger = await _register(client, f"stranger_{uuid.uuid4().hex[:8]}@example.com")
        res = await client.delete(f"/capture-devices/{other['device_id']}", headers=_auth(stranger))
        assert res.status_code == 404

        assert (await client.post("/capture-devices/self/revoke", headers=_auth(mine["key"]))).status_code == 204
        assert (await client.get("/students", headers=_auth(mine["key"]))).status_code == 401
        assert (await client.get("/students", headers=_auth(other["key"]))).status_code == 200


@pytest.mark.anyio
async def test_cancel_and_unknown_codes():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, guardian, _child = await _guardian_with_child(client)
        started = (await client.post("/capture-devices/start", json={"client_name": "Backpack Capture"})).json()

        # The approval page needs a signed-in person.
        assert (await client.get(f"/capture-devices/requests/{started['user_code']}")).status_code == 401
        page = await client.get(f"/capture-devices/requests/{started['user_code'].lower()}", headers=_auth(guardian))
        assert page.json()["status"] == "pending" and page.json()["client_name"] == "Backpack Capture"

        denied = await client.post(f"/capture-devices/requests/{started['user_code']}/deny", headers=_auth(guardian))
        assert denied.json()["status"] == "denied"
        token = await client.post("/capture-devices/token", json={"device_code": started["device_code"]})
        assert token.json()["status"] == "denied"
        # Answered once is answered.
        late = await client.post(f"/capture-devices/requests/{started['user_code']}/approve", headers=_auth(guardian))
        assert late.status_code == 410

        assert (await client.get("/capture-devices/requests/BBBB-CCCC", headers=_auth(guardian))).status_code == 404
        unknown = await client.post("/capture-devices/token", json={"device_code": "not-a-code"})
        assert unknown.json()["status"] == "expired"


async def _admin(client: AsyncClient) -> str:
    email = f"diag_admin_{uuid.uuid4().hex[:8]}@example.com"
    token = await _register(client, email)
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return token


@pytest.mark.anyio
async def test_send_logs_to_schoolz_and_an_admin_reads_them_back():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, guardian, _child = await _guardian_with_child(client)
        key = _auth((await _connect(client, guardian))["key"])
        log = [
            {"t": "2026-10-22T20:00:00Z", "e": "run_start", "manual": True},
            {"t": "2026-10-22T20:00:09Z", "e": "left_classroom", "index": 1},
        ]
        sent = await client.post(
            "/capture-devices/diagnostics",
            json={"extension_version": "0.9.1", "platform": "Windows", "log": log, "last_run": {"status": "done"}},
            headers=key,
        )
        assert sent.status_code == 200, sent.text
        body = sent.json()
        assert body["reference"] == body["id"][:8].upper()
        # From a signed-in browser too (the popup of a password-signed-in extension).
        assert (
            await client.post("/capture-devices/diagnostics", json={"extension_version": "0.9.1", "log": []}, headers=_auth(guardian))
        ).status_code == 200

        # Only admins with kids.view read them back; the key can't, nor can the guardian.
        assert (await client.get("/capture-devices/diagnostics", headers=key)).status_code == 403
        assert (await client.get("/capture-devices/diagnostics", headers=_auth(guardian))).status_code == 403
        admin = _auth(await _admin(client))
        listed = (await client.get(f"/capture-devices/diagnostics?reference={body['reference'].lower()}", headers=admin)).json()
        assert [d["id"] for d in listed] == [body["id"]]
        assert listed[0]["user_email"] == email
        assert listed[0]["device_name"] == "Backpack Capture on Windows"
        assert listed[0]["entries"] == 2
        full = (await client.get(f"/capture-devices/diagnostics/{body['id']}", headers=admin)).json()
        assert full["payload"] == {"platform": "Windows", "log": log, "last_run": {"status": "done"}}


@pytest.mark.anyio
async def test_logs_are_capped_in_size_and_kept_thirty_days():
    from datetime import UTC, datetime, timedelta

    from models import CaptureDiagnostic

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, guardian, _child = await _guardian_with_child(client)
        key = _auth((await _connect(client, guardian))["key"])
        big = [{"e": "x" * 1000}] * 600
        too_big = await client.post("/capture-devices/diagnostics", json={"extension_version": "0.9.1", "log": big}, headers=key)
        assert too_big.status_code == 413

        async with database.SessionLocal() as db:
            user_id = (await db.execute(select(User.id).where(User.email == _email))).scalar_one()
            old = CaptureDiagnostic(
                user_id=user_id,
                created_at=datetime.now(UTC) - timedelta(days=31),
                extension_version="0.9.0",
                payload={"log": []},
            )
            db.add(old)
            await db.commit()
            old_id = old.id
        assert (await client.post("/capture-devices/diagnostics", json={"extension_version": "0.9.1", "log": []}, headers=key)).status_code == 200
        async with database.SessionLocal() as db:
            assert await db.get(CaptureDiagnostic, old_id) is None
