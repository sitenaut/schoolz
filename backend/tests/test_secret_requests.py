import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import SecretAccessRequest
from tests.test_admin_users import _register
from tests.test_api_keys import _bearer, _create_key

pytestmark = pytest.mark.anyio

UNLOCK = "unlock-key-for-tests"


@pytest.fixture(autouse=True)
def _unlock_key(monkeypatch):
    monkeypatch.setenv("SECRETS_UNLOCK_KEY", UNLOCK)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _body(**over) -> dict:
    return {
        "client_name": "Claude Code on test",
        "reason": "Sync Fly secrets for the scraper",
        "command": "scripts/sync-fly-secrets.sh schoolz-scraper",
        "secret_names": ["SCRAPER_API_KEY", "OTEL_EXPORTER_OTLP_ENDPOINT"],
        **over,
    }


async def _start(client: AsyncClient, key: dict, **over) -> dict:
    res = await client.post("/admin/secret-requests", headers=_bearer(key), json=_body(**over))
    assert res.status_code == 201, res.text
    return res.json()


async def _poll(client: AsyncClient, key: dict, started: dict):
    return await client.post("/admin/secret-requests/poll", headers=_bearer(key), json={"device_code": started["device_code"]})


async def _setup(client: AsyncClient, prefix: str) -> tuple[dict, dict]:
    boss, _ = await _register(client, prefix, super_admin=True)
    return boss, await _create_key(client, boss, ["scans.view"])


async def _set_expiry(user_code: str, when: datetime) -> None:
    async with database.SessionLocal() as db:
        await db.execute(update(SecretAccessRequest).where(SecretAccessRequest.user_code == user_code).values(expires_at=when))
        await db.commit()


async def test_approved_request_hands_over_the_unlock_key_exactly_once():
    async with _client() as client:
        boss, key = await _setup(client, "secreq")
        started = await _start(client, key)
        assert started["user_code"] and started["expires_in"] == 600

        pending = (await _poll(client, key, started)).json()
        assert pending["status"] == "pending" and pending["unlock_key"] is None

        seen = (await client.get(f"/admin/secret-requests/{started['user_code']}", headers=boss)).json()
        assert seen["status"] == "pending"
        assert seen["reason"] == "Sync Fly secrets for the scraper"
        assert seen["command"] == "scripts/sync-fly-secrets.sh schoolz-scraper"
        assert seen["secret_names"] == ["OTEL_EXPORTER_OTLP_ENDPOINT", "SCRAPER_API_KEY"]
        assert seen["api_key_name"] == "claude"

        approved = await client.post(f"/admin/secret-requests/{started['user_code']}/approve", headers=boss)
        assert approved.status_code == 200 and approved.json()["status"] == "approved"
        assert approved.json()["decided_by"] is not None

        got = (await _poll(client, key, started)).json()
        assert got["status"] == "approved" and got["unlock_key"] == UNLOCK
        assert got["command"] == "scripts/sync-fly-secrets.sh schoolz-scraper"
        assert got["secret_names"] == ["OTEL_EXPORTER_OTLP_ENDPOINT", "SCRAPER_API_KEY"]

        again = (await _poll(client, key, started)).json()
        assert again["status"] == "expired" and again["unlock_key"] is None

        log = (await client.get("/admin/secret-requests", headers=boss)).json()
        mine = next(r for r in log if r["user_code"] == started["user_code"])
        assert mine["status"] == "collected" and mine["collected_at"] is not None


async def test_the_unlock_key_and_device_code_are_never_stored():
    async with _client() as client:
        boss, key = await _setup(client, "secstore")
        started = await _start(client, key)
        await client.post(f"/admin/secret-requests/{started['user_code']}/approve", headers=boss)
        await _poll(client, key, started)
        async with database.SessionLocal() as db:
            row = (
                await db.execute(select(SecretAccessRequest).where(SecretAccessRequest.user_code == started["user_code"]))
            ).scalar_one()
            stored = repr({k: v for k, v in row.__dict__.items() if not k.startswith("_")})
        assert UNLOCK not in stored and started["device_code"] not in stored


async def test_a_denied_request_gets_nothing():
    async with _client() as client:
        boss, key = await _setup(client, "secdeny")
        started = await _start(client, key)
        denied = await client.post(f"/admin/secret-requests/{started['user_code']}/deny", headers=boss)
        assert denied.status_code == 200 and denied.json()["status"] == "denied"

        got = (await _poll(client, key, started)).json()
        assert got["status"] == "denied" and got["unlock_key"] is None
        # Answered once; it can't be flipped afterwards.
        assert (await client.post(f"/admin/secret-requests/{started['user_code']}/approve", headers=boss)).status_code == 410


async def test_a_session_cannot_approve_its_own_request_and_outsiders_are_refused():
    async with _client() as client:
        boss, key = await _setup(client, "secauth")
        started = await _start(client, key)
        code = started["user_code"]

        # An API key (even a super admin's) never reaches the decision endpoints or the log.
        assert (await client.post(f"/admin/secret-requests/{code}/approve", headers=_bearer(key))).status_code == 403
        assert (await client.post(f"/admin/secret-requests/{code}/deny", headers=_bearer(key))).status_code == 403
        assert (await client.get(f"/admin/secret-requests/{code}", headers=_bearer(key))).status_code == 403
        assert (await client.get("/admin/secret-requests", headers=_bearer(key))).status_code == 403
        assert (await _poll(client, key, started)).json()["status"] == "pending"

        # Anonymous, and an ordinary user, can neither ask nor read.
        assert (await client.post("/admin/secret-requests", json=_body())).status_code == 401
        nobody, _ = await _register(client, "secnobody")
        assert (await client.post("/admin/secret-requests", headers=nobody, json=_body())).status_code == 403
        assert (await client.get("/admin/secret-requests", headers=nobody)).status_code == 403
        assert (await client.post(f"/admin/secret-requests/{code}/approve", headers=nobody)).status_code == 403

        # A key whose creator is no longer a super admin can't ask.
        helper, helper_id = await _register(client, "sechelper", super_admin=True)
        helper_key = await _create_key(client, helper, ["scans.view"])
        from models import User

        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.id == helper_id).values(is_admin=False))
            await db.commit()
        assert (await client.post("/admin/secret-requests", headers=_bearer(helper_key), json=_body())).status_code == 403


async def test_only_the_key_that_asked_can_collect():
    async with _client() as client:
        boss, key = await _setup(client, "secbind")
        other_key = await _create_key(client, boss, ["scans.view"])
        other_boss, stranger = await _setup(client, "secstranger")

        started = await _start(client, key)
        await client.post(f"/admin/secret-requests/{started['user_code']}/approve", headers=boss)

        for thief in (other_key, stranger):
            got = (await _poll(client, thief, started)).json()
            assert got["status"] == "expired" and got["unlock_key"] is None
        # The thwarted attempts consumed nothing.
        assert (await _poll(client, key, started)).json()["unlock_key"] == UNLOCK


async def test_requests_expire_before_and_after_approval():
    async with _client() as client:
        boss, key = await _setup(client, "secexp")
        past = datetime.now(timezone.utc) - timedelta(seconds=1)

        stale = await _start(client, key)
        await _set_expiry(stale["user_code"], past)
        assert (await _poll(client, key, stale)).json()["status"] == "expired"
        assert (await client.post(f"/admin/secret-requests/{stale['user_code']}/approve", headers=boss)).status_code == 410
        listed = (await client.get(f"/admin/secret-requests/{stale['user_code']}", headers=boss)).json()
        assert listed["status"] == "expired"

        # Approved, but not collected within the window.
        late = await _start(client, key)
        await client.post(f"/admin/secret-requests/{late['user_code']}/approve", headers=boss)
        await _set_expiry(late["user_code"], past)
        got = (await _poll(client, key, late)).json()
        assert got["status"] == "expired" and got["unlock_key"] is None


async def test_a_missing_server_key_fails_loudly_without_spending_the_approval(monkeypatch):
    async with _client() as client:
        boss, key = await _setup(client, "secnokey")
        started = await _start(client, key)
        await client.post(f"/admin/secret-requests/{started['user_code']}/approve", headers=boss)

        monkeypatch.delenv("SECRETS_UNLOCK_KEY")
        assert (await _poll(client, key, started)).status_code == 503

        monkeypatch.setenv("SECRETS_UNLOCK_KEY", UNLOCK)
        assert (await _poll(client, key, started)).json()["unlock_key"] == UNLOCK


async def test_requests_are_validated_and_capped():
    async with _client() as client:
        boss, key = await _setup(client, "secval")
        for bad in (
            {"secret_names": []},
            {"secret_names": ["lowercase_name"]},
            {"secret_names": ["HAS-DASH"]},
            {"secret_names": ["FINE_NAME", "op://vault/item"]},
            {"reason": "   "},
            {"command": ""},
            {"reason": "x" * 301},
        ):
            res = await client.post("/admin/secret-requests", headers=_bearer(key), json=_body(**bad))
            assert res.status_code == 422, (bad, res.text)

        # Duplicate names collapse.
        dup = await _start(client, key, secret_names=["B_SECRET", "A_SECRET", "B_SECRET"])
        seen = (await client.get(f"/admin/secret-requests/{dup['user_code']}", headers=boss)).json()
        assert seen["secret_names"] == ["A_SECRET", "B_SECRET"]

        for _ in range(4):
            await _start(client, key)
        assert (await client.post("/admin/secret-requests", headers=_bearer(key), json=_body())).status_code == 429
