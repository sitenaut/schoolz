import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import ApiKey, ApiKeyRequest, ScheduledJob, User
from routers.admin_config import merge_local_event_sources
from tests.test_admin_users import _register

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _create_key(client: AsyncClient, boss: dict, permissions: list[str], **extra) -> dict:
    res = await client.post("/admin/api-keys", headers=boss, json={"name": "claude", "permissions": permissions, **extra})
    assert res.status_code == 201, res.text
    return res.json()


def _bearer(key: dict) -> dict:
    return {"authorization": f"Bearer {key['key']}"}


async def test_a_key_is_scoped_to_its_permissions_and_never_reaches_super_admin_endpoints():
    async with _client() as client:
        boss, _ = await _register(client, "keyboss", super_admin=True)
        key = await _create_key(client, boss, ["scans.view"])
        assert key["key"].startswith("szk_") and key["key_prefix"] == key["key"][:12]

        me = (await client.get("/auth/me", headers=_bearer(key))).json()
        assert me["is_admin"] is False and me["permissions"] == ["scans.view"]

        assert (await client.get("/scheduled-jobs", headers=_bearer(key))).status_code == 200
        assert (await client.post("/scheduled-jobs/test-fetch", headers=_bearer(key), json={"kind": "x", "params": {}})).status_code == 403
        assert (await client.get("/survey/responses", headers=_bearer(key))).status_code == 403
        # Super-admin-only, even though the key's creator is a super admin.
        assert (await client.get("/admin/roles", headers=_bearer(key))).status_code == 403
        assert (await client.post("/admin/api-keys", headers=_bearer(key), json={"name": "x", "permissions": ["scans.view"]})).status_code == 403

        listed = (await client.get("/admin/api-keys", headers=boss)).json()
        mine = next(k for k in listed if k["id"] == key["id"])
        assert "key" not in mine and mine["last_used_at"] is not None


async def test_only_the_hash_is_stored_and_revoked_or_expired_keys_are_rejected():
    async with _client() as client:
        boss, _ = await _register(client, "keyrevoke", super_admin=True)
        key = await _create_key(client, boss, ["scans.view"], expires_in_days=None)
        async with database.SessionLocal() as db:
            row = (await db.execute(select(ApiKey).where(ApiKey.id == key["id"]))).scalar_one()
            assert row.key_hash != key["key"] and key["key"] not in row.key_hash and row.expires_at is None

        expiring = await _create_key(client, boss, ["scans.view"])
        async with database.SessionLocal() as db:
            await db.execute(
                update(ApiKey).where(ApiKey.id == expiring["id"]).values(expires_at=datetime.now(timezone.utc) - timedelta(minutes=1))
            )
            await db.commit()
        assert (await client.get("/scheduled-jobs", headers=_bearer(expiring))).status_code == 401

        assert (await client.delete(f"/admin/api-keys/{key['id']}", headers=boss)).status_code == 204
        assert (await client.get("/scheduled-jobs", headers=_bearer(key))).status_code == 401
        assert (await client.get("/scheduled-jobs", headers={"authorization": "Bearer szk_not-a-real-key"})).status_code == 401


async def test_a_key_shrinks_with_its_creator():
    async with _client() as client:
        boss, boss_id = await _register(client, "keydemote", super_admin=True)
        key = await _create_key(client, boss, ["scans.manage"])
        assert (await client.get("/scheduled-jobs", headers=_bearer(key))).status_code == 200
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.id == boss_id).values(is_admin=False))
            await db.commit()
        assert (await client.get("/scheduled-jobs", headers=_bearer(key))).status_code == 403


async def test_non_super_admins_cannot_create_keys():
    async with _client() as client:
        helper, _ = await _register(client, "keyhelper")
        res = await client.post("/admin/api-keys", headers=helper, json={"name": "x", "permissions": ["scans.view"]})
        assert res.status_code == 403


def test_merge_local_event_sources_upserts_by_name_and_never_removes():
    params = {
        "rss_sources": [{"name": "a", "url": "u1"}, {"name": "keep", "url": "k"}],
        "evvnt_sources": [{"name": "e"}],
    }
    merged, added, updated = merge_local_event_sources(
        params,
        {"rss_sources": [{"name": "a", "url": "u2"}, {"name": "keep", "url": "k"}, {"name": "new", "url": "n"}], "tribe_sources": [{"name": "t"}]},
    )
    assert (added, updated) == (2, 1)
    assert merged["rss_sources"] == [{"name": "a", "url": "u2"}, {"name": "keep", "url": "k"}, {"name": "new", "url": "n"}]
    assert merged["tribe_sources"] == [{"name": "t"}] and merged["evvnt_sources"] == [{"name": "e"}]
    assert params["rss_sources"][0]["url"] == "u1"


async def test_config_import_seeds_local_event_sources_with_a_key():
    job_name = f"Local events refresh {uuid.uuid4().hex[:6]}"
    async with database.SessionLocal() as db:
        db.add(ScheduledJob(kind="local_events.refresh", name=job_name, cron_expr="0 5 * * *", params={"rss_sources": [{"name": "old"}]}))
        await db.commit()

    body = {
        "exported_at": "2026-09-30T12:00:00Z",
        "source": "test",
        "districts": [],
        "schools": [],
        "smore_newsletters": [],
        "local_events": {job_name: {"rss_sources": [{"name": "new", "url": "https://example.com/feed"}]}, "No such job": {"rss_sources": [{"name": "x"}]}},
    }
    async with _client() as client:
        boss, _ = await _register(client, "keyimport", super_admin=True)
        viewer = await _create_key(client, boss, ["scans.manage"])
        assert (await client.post("/admin/config/import", headers=_bearer(viewer), json=body)).status_code == 403

        key = await _create_key(client, boss, ["config.manage"])
        res = await client.post("/admin/config/import", headers=_bearer(key), json=body)
        assert res.status_code == 200, res.text
        out = res.json()
        assert out["local_event_sources_added"] == 1 and out["local_event_jobs_missing"] == ["No such job"]

        bad = await client.post("/admin/config/import", headers=_bearer(key), json={**body, "local_events": {job_name: {"rss": [{"name": "x"}]}}})
        assert bad.status_code == 422

    async with database.SessionLocal() as db:
        job = (await db.execute(select(ScheduledJob).where(ScheduledJob.name == job_name))).scalar_one()
        assert [s["name"] for s in job.params["rss_sources"]] == ["old", "new"]


# ---- Device flow --------------------------------------------------------------


async def _start(client: AsyncClient, name: str = "Claude Code on test") -> dict:
    res = await client.post("/auth/device/start", json={"client_name": name})
    assert res.status_code == 200, res.text
    return res.json()


async def _poll(client: AsyncClient, device_code: str) -> dict:
    res = await client.post("/auth/device/token", json={"device_code": device_code})
    assert res.status_code == 200, res.text
    return res.json()


async def test_device_flow_issues_a_scoped_key_exactly_once_after_approval():
    async with _client() as client:
        boss, boss_id = await _register(client, "devboss", super_admin=True)
        started = await _start(client)
        code = started["user_code"]
        assert len(code) == 9 and code[4] == "-"
        assert await _poll(client, started["device_code"]) == {"status": "pending", "key": None, "key_prefix": None, "permissions": None}

        # Codes are matched case- and dash-insensitively, as typed on a phone.
        seen = await client.get(f"/admin/api-keys/requests/{code.replace('-', '').lower()}", headers=boss)
        assert seen.status_code == 200 and seen.json()["client_name"] == "Claude Code on test" and seen.json()["status"] == "pending"

        approved = await client.post(
            f"/admin/api-keys/requests/{code}/approve", headers=boss, json={"permissions": ["scans.view"], "expires_in_days": 30}
        )
        assert approved.status_code == 200 and approved.json()["status"] == "approved"

        got = await _poll(client, started["device_code"])
        assert got["status"] == "approved" and got["key"].startswith("szk_") and got["permissions"] == ["scans.view"]
        # Collected once; the device code is spent.
        assert (await _poll(client, started["device_code"]))["status"] == "expired"
        assert (await client.get(f"/admin/api-keys/requests/{code}", headers=boss)).json()["status"] == "issued"

        headers = {"authorization": f"Bearer {got['key']}"}
        me = (await client.get("/auth/me", headers=headers)).json()
        assert me["id"] == boss_id and me["permissions"] == ["scans.view"] and me["is_admin"] is False
        listed = next(k for k in (await client.get("/admin/api-keys", headers=boss)).json() if k["key_prefix"] == got["key_prefix"])
        assert listed["name"] == "Claude Code on test" and listed["expires_at"] is not None

        # Already answered: can't be approved again.
        again = await client.post(f"/admin/api-keys/requests/{code}/approve", headers=boss, json={"permissions": ["scans.manage"]})
        assert again.status_code == 410


async def test_device_flow_denied_expired_and_unauthorized_approvals():
    async with _client() as client:
        boss, _ = await _register(client, "devdeny", super_admin=True)
        helper, _ = await _register(client, "devhelper")

        denied = await _start(client)
        assert (await client.post(f"/admin/api-keys/requests/{denied['user_code']}/approve", headers=helper, json={"permissions": ["scans.view"]})).status_code == 403
        assert (await client.post(f"/admin/api-keys/requests/{denied['user_code']}/deny", headers=boss)).status_code == 200
        assert (await _poll(client, denied["device_code"]))["status"] == "denied"

        stale = await _start(client)
        async with database.SessionLocal() as db:
            await db.execute(
                update(ApiKeyRequest)
                .where(ApiKeyRequest.user_code == stale["user_code"])
                .values(expires_at=datetime.now(timezone.utc) - timedelta(seconds=1))
            )
            await db.commit()
        assert (await client.post(f"/admin/api-keys/requests/{stale['user_code']}/approve", headers=boss, json={"permissions": ["scans.view"]})).status_code == 410
        assert (await client.get(f"/admin/api-keys/requests/{stale['user_code']}", headers=boss)).json()["status"] == "expired"
        assert (await _poll(client, stale["device_code"]))["status"] == "expired"
        assert (await _poll(client, "not-a-real-device-code"))["status"] == "expired"

        # A key can't approve a login request, even one its creator could.
        key = await _create_key(client, boss, ["config.manage"])
        pending = await _start(client)
        res = await client.post(f"/admin/api-keys/requests/{pending['user_code']}/approve", headers=_bearer(key), json={"permissions": ["config.manage"]})
        assert res.status_code == 403

        async with database.SessionLocal() as db:
            row = (await db.execute(select(ApiKeyRequest).where(ApiKeyRequest.user_code == pending["user_code"]))).scalar_one()
            assert pending["device_code"] not in row.device_code_hash
