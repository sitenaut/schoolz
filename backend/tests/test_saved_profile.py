"""Localz saved services profile (routers/saved_profile.py): owner only,
consent first, hard delete, encrypted at rest, never logged, and never
anywhere near the shared Student / guardian / notification model."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import logging
import re
import uuid

import pytest
from cryptography.fernet import Fernet
from fastapi.routing import APIRoute, iter_route_contexts
from httpx import ASGITransport, AsyncClient
from sqlalchemy import event, func, select, text

import crypto
import database
from main import app
from models import ConsentRecord, District, GuardianStudentLink, Notification, School, ServicesProfile, Student, User
from permissions import PERMISSION_KEYS
from resources import saved_profile as sp
from tests.test_admin_users import _register

pytestmark = pytest.mark.anyio

URL = "/me/saved-answers"
ANSWERS = {"ages": ["18-59", "1-4"], "has": ["pregnant_or_new_baby", "veteran_military"], "focus": ["survivors", "lgbtq"], "noStatusFirst": True}
# Every value that could identify what someone saved. None may reach a log.
SENSITIVE = ["pregnant_or_new_baby", "veteran_military", "survivors", "lgbtq", "noStatusFirst", "1-4", "18-59"]


@pytest.fixture(autouse=True)
def _key(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("ENCRYPTION_REQUIRE", "false")


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _consent(client, headers, version=None):
    return await client.post(f"{URL}/consent", headers=headers, json={"purpose": "services_profile", "policy_version": version or sp.POLICY_VERSION})


async def _save(client, headers, answers=ANSWERS):
    return await client.put(URL, headers=headers, json=answers)


async def test_anonymous_callers_get_nothing():
    async with _client() as client:
        for method in ("GET", "PUT", "DELETE"):
            assert (await client.request(method, URL, json=ANSWERS)).status_code == 401
        assert (await client.post(f"{URL}/consent", json={"purpose": "services_profile", "policy_version": 1})).status_code == 401
        assert (await client.delete(f"{URL}/consent")).status_code == 401


async def test_consent_first_then_save_read_and_delete():
    async with _client() as client:
        me, _ = await _register(client, "sp_flow")
        state = (await client.get(URL, headers=me)).json()
        assert state["available"] is True and state["consent"] is None and state["saved"] is False

        refused = await _save(client, me)
        assert refused.status_code == 409 and refused.json()["code"] == "consent_required"

        granted = (await _consent(client, me)).json()
        assert granted["consent"]["current"] is True and granted["saved"] is False
        saved = await _save(client, me)
        assert saved.status_code == 200, saved.text
        assert saved.json()["answers"] == ANSWERS

        got = (await client.get(URL, headers=me)).json()
        assert got["answers"] == ANSWERS and got["last_used_at"]

        assert (await client.delete(URL, headers=me)).status_code == 204
        after = (await client.get(URL, headers=me)).json()
        assert after["saved"] is False and after["answers"] is None and after["consent"] is None


async def test_withdrawing_consent_hard_deletes_the_profile():
    async with _client() as client:
        me, uid = await _register(client, "sp_withdraw")
        await _consent(client, me)
        await _save(client, me)
        assert (await client.delete(f"{URL}/consent", headers=me)).status_code == 204
        async with database.SessionLocal() as db:
            assert await db.get(ServicesProfile, uid) is None
            rows = (await db.execute(select(ConsentRecord).where(ConsentRecord.user_id == uid))).scalars().all()
            assert rows and all(r.withdrawn_at is not None for r in rows)
        assert (await _save(client, me)).json()["code"] == "consent_required"


async def test_a_policy_version_bump_asks_for_consent_again(monkeypatch):
    async with _client() as client:
        me, _ = await _register(client, "sp_policy")
        await _consent(client, me)
        await _save(client, me)
        monkeypatch.setattr(sp, "POLICY_VERSION", sp.POLICY_VERSION + 1)

        state = (await client.get(URL, headers=me)).json()
        assert state["consent"]["current"] is False and state["saved"] is True and state["answers"] is None
        assert (await _save(client, me)).json()["code"] == "consent_required"
        stale = await _consent(client, me, version=sp.POLICY_VERSION - 1)
        assert stale.status_code == 409 and stale.json()["code"] == "policy_changed"

        assert (await _consent(client, me)).json()["consent"]["current"] is True
        assert (await client.get(URL, headers=me)).json()["answers"] == ANSWERS


async def test_alert_purposes_cant_be_granted_yet():
    async with _client() as client:
        me, _ = await _register(client, "sp_alerts")
        res = await client.post(f"{URL}/consent", headers=me, json={"purpose": "services_alerts", "policy_version": sp.POLICY_VERSION})
        assert res.status_code == 400
        res = await client.post(f"{URL}/consent", headers=me, json={"purpose": "anything", "policy_version": sp.POLICY_VERSION})
        assert res.status_code == 422


async def test_no_one_else_can_read_overwrite_or_delete_a_profile():
    async with _client() as client:
        a, a_id = await _register(client, "sp_owner")
        b, _ = await _register(client, "sp_other")
        boss, _ = await _register(client, "sp_boss", super_admin=True)
        await _consent(client, a)
        await _save(client, a)

        # B and a super admin only ever see their own (empty) profile, and
        # writing or deleting touches only theirs.
        for other in (b, boss):
            assert (await client.get(URL, headers=other)).json()["saved"] is False
            await _consent(client, other)
            await _save(client, other, {"ages": ["60+"]})
            assert (await client.delete(URL, headers=other)).status_code == 204
            assert (await client.delete(f"{URL}/consent", headers=other)).status_code == 204
        # No route takes a user id, so there's nothing to aim at A with.
        assert (await client.get(f"{URL}/{a_id}", headers=boss)).status_code in (404, 405)
        assert (await client.get(URL, headers=a)).json()["answers"] == ANSWERS

        # An API key, even a super admin's with every permission, is refused.
        made = await client.post("/admin/api-keys", headers=boss, json={"name": "sp", "permissions": sorted(PERMISSION_KEYS)})
        assert made.status_code == 201, made.text
        key = {"authorization": f"Bearer {made.json()['key']}"}
        for method in ("GET", "PUT", "DELETE"):
            assert (await client.request(method, URL, headers=key, json=ANSWERS)).status_code == 403
        assert (await client.post(f"{URL}/consent", headers=key, json={"purpose": "services_profile", "policy_version": 1})).status_code == 403
        assert (await client.get(URL, headers=a)).json()["answers"] == ANSWERS


def test_no_permission_or_other_route_reaches_profiles():
    assert not [k for k in PERMISSION_KEYS if "profile" in k or "services" in k or "consent" in k]
    paths = [c.original_route.path for c in iter_route_contexts(app.routes) if isinstance(c.original_route, APIRoute)]
    mine = [p for p in paths if p.startswith(URL)]
    assert sorted(set(mine)) == [URL, f"{URL}/consent"]
    # Nothing outside the owner's own routes mentions the profile.
    assert not [p for p in paths if ("saved-answers" in p or "services-profile" in p) and not p.startswith(URL)]


async def test_the_stored_column_is_ciphertext():
    async with _client() as client:
        me, uid = await _register(client, "sp_cipher")
        await _consent(client, me)
        await _save(client, me)
        async with database.SessionLocal() as db:
            raw = (await db.execute(text("SELECT profile FROM services_profiles WHERE user_id = :u"), {"u": uid})).scalar_one()
        assert crypto.is_encrypted(raw)
        for value in SENSITIVE + ["ages", "has", "focus"]:
            assert value not in raw
        # Not the Gmail tokens' key: the plain configured key can't open it.
        with pytest.raises(crypto.EncryptionError):
            crypto.decrypt(raw)


async def test_without_an_encryption_key_nothing_is_saved(monkeypatch):
    async with _client() as client:
        me, uid = await _register(client, "sp_nokey")
        monkeypatch.delenv("DATA_ENCRYPTION_KEYS")
        assert (await client.get(URL, headers=me)).json()["available"] is False
        await _consent(client, me)
        res = await _save(client, me)
        assert res.status_code == 503 and res.json()["code"] == "encryption_unavailable"
        async with database.SessionLocal() as db:
            assert await db.get(ServicesProfile, uid) is None


@pytest.mark.parametrize(
    "body",
    [
        {"ages": ["18-59"], "income": 30000},
        {"ages": ["adult"]},
        {"has": ["immigration_status"]},
        {"focus": ["women", "women"]},
        {"ages": ["18-59"] * 50},
        {"noStatusFirst": "yes please"},
        {"notes": "free text"},
    ],
)
async def test_validation_refuses_anything_the_sheet_doesnt_ask(body):
    async with _client() as client:
        me, uid = await _register(client, "sp_valid")
        await _consent(client, me)
        assert (await _save(client, me, body)).status_code == 422
        async with database.SessionLocal() as db:
            assert await db.get(ServicesProfile, uid) is None


async def test_saving_nothing_forgets():
    async with _client() as client:
        me, uid = await _register(client, "sp_empty")
        await _consent(client, me)
        await _save(client, me)
        res = await _save(client, me, {})
        assert res.status_code == 200 and res.json()["saved"] is False
        async with database.SessionLocal() as db:
            assert await db.get(ServicesProfile, uid) is None


_NOISE = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}|\d{4}-\d{2}-\d{2}[T ][\d:.+]*", re.I)


async def test_profile_routes_never_log_a_field_or_value(caplog):
    caplog.set_level(logging.DEBUG)
    async with _client() as client:
        me, _ = await _register(client, "sp_logs")
        caplog.clear()
        await client.get(URL, headers=me)
        await _save(client, me)  # refused: no consent yet
        await _consent(client, me)
        await _save(client, me)
        await client.get(URL, headers=me)
        await _save(client, me, {"ages": ["18-59"], "has": ["pregnant_or_new_baby"], "notes": "survivors lgbtq"})  # 422
        await client.delete(URL, headers=me)
        await client.delete(f"{URL}/consent", headers=me)
    # The request log line is captured (so this checks something real).
    assert [r for r in caplog.records if r.getMessage() == "http_request" and getattr(r, "path", "") == URL]
    for record in caplog.records:
        blob = record.getMessage() + " " + " ".join(f"{k}={v!r}" for k, v in vars(record).items())
        # Ids and timestamps first: a uuid4's third group always starts with
        # 4, so about one id in sixteen contains "1-4" by chance.
        blob = _NOISE.sub("<x>", blob)
        for value in SENSITIVE:
            assert value not in blob, f"{value!r} reached the log via {record.name}: {record.getMessage()}"


async def test_profile_never_touches_students_links_or_notifications():
    """A co-parent linked to the same child sees nothing and hears nothing."""
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Profile District {run}")
        db.add(district)
        await db.flush()
        school = School(name=f"Profile Elementary {run}", slug=f"profile-elem-{run}", school_type="elementary", district_id=district.id)
        db.add(school)
        await db.commit()
        school_id = school.id

    async with _client() as client:
        a, _ = await _register(client, "sp_parent_a")
        b, _ = await _register(client, "sp_parent_b")
        kid = {"first_name": "Pro", "last_name": "File", "student_id": f"p-{run}", "school_id": school_id}
        assert (await client.post("/students", json=kid, headers=a)).status_code == 201
        assert (await client.post("/students", json=kid, headers=b)).status_code == 201

        async def counts():
            async with database.SessionLocal() as db:
                return [await db.scalar(select(func.count()).select_from(m)) for m in (Student, GuardianStudentLink, Notification)]

        before = await counts()
        b_heard = (await client.get("/notifications", headers=b)).json()
        touched: list[str] = []
        seen_profile: list[str] = []

        def watch(conn, cursor, statement, params, context, executemany):
            low = statement.lower()
            if "services_profiles" in low:
                seen_profile.append(statement)
            for table in ("students", "guardian_student_links", "notifications"):
                if f" {table}" in low or f'"{table}"' in low:
                    touched.append(statement)

        sync_engine = database.engine.sync_engine
        event.listen(sync_engine, "before_cursor_execute", watch)
        try:
            await client.get(URL, headers=a)
            await _consent(client, a)
            await _save(client, a)
            await client.get(URL, headers=a)
            await _save(client, a, {"has": ["disability"]})
            await client.delete(URL, headers=a)
            await _consent(client, a)
            await _save(client, a)
        finally:
            event.remove(sync_engine, "before_cursor_execute", watch)
        assert seen_profile, "the statement watcher saw nothing"
        assert touched == [], touched[0] if touched else ""
        assert await counts() == before
        # The co-parent sees no profile and no notification about it.
        assert (await client.get(URL, headers=b)).json()["saved"] is False
        assert (await client.get("/notifications", headers=b)).json() == b_heard


async def test_profile_read_never_returns_another_users_row_even_if_present():
    """Belt and braces: with two rows in the table, each owner reads only theirs."""
    async with _client() as client:
        a, _ = await _register(client, "sp_two_a")
        b, _ = await _register(client, "sp_two_b")
        for who, answers in ((a, {"ages": ["60+"]}), (b, {"ages": ["u1"]})):
            await _consent(client, who)
            await _save(client, who, answers)
        assert (await client.get(URL, headers=a)).json()["answers"]["ages"] == ["60+"]
        assert (await client.get(URL, headers=b)).json()["answers"]["ages"] == ["u1"]


async def test_a_user_row_delete_cascades():
    async with _client() as client:
        me, uid = await _register(client, "sp_cascade")
        await _consent(client, me)
        await _save(client, me)
    async with database.SessionLocal() as db:
        await db.execute(text("DELETE FROM users WHERE id = :u"), {"u": uid})
        await db.commit()
        assert await db.get(ServicesProfile, uid) is None
        assert (await db.execute(select(ConsentRecord).where(ConsentRecord.user_id == uid))).first() is None
        assert await db.get(User, uid) is None
