"""Two-step sign-in for admins (SZ-18): on Supabase auth an admin endpoint
needs an aal2 session. Logged only until MFA_ENFORCE is on; guardians, API
keys and local auth are never asked."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import logging
import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import auth
import database
from main import app
from models import User

pytestmark = pytest.mark.anyio


@pytest.fixture
def supabase(monkeypatch):
    """Supabase mode with tokens of the form "<sub>|<aal>"."""
    monkeypatch.setattr(auth, "AUTH_MODE", "supabase")
    monkeypatch.delenv("MFA_ENFORCE", raising=False)
    auth._mfa_logged.clear()

    async def verify(token):
        sub, aal = token.split("|")
        return {"sub": sub, "email": f"{sub}@example.com", "aal": aal}

    monkeypatch.setattr(auth, "_verify_supabase_token", verify)


async def _admin(super_admin: bool = True) -> str:
    sub = f"mfa-{uuid.uuid4().hex[:8]}"
    async with database.SessionLocal() as db:
        user = await auth._get_or_create_supabase_user(db, {"sub": sub, "email": f"{sub}@example.com"})
        await db.execute(update(User).where(User.id == user.id).values(is_admin=super_admin))
        await db.commit()
    return sub


def _h(sub: str, aal: str) -> dict:
    return {"Authorization": f"Bearer {sub}|{aal}"}


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_log_mode_lets_aal1_through_and_logs_once(supabase, caplog):
    sub = await _admin()
    async with _client() as client:
        with caplog.at_level(logging.WARNING, logger="auth"):
            for _ in range(3):
                assert (await client.get("/scheduled-jobs", headers=_h(sub, "aal1"))).status_code == 200
        me = (await client.get("/auth/me", headers=_h(sub, "aal1"))).json()
    assert [r.message for r in caplog.records].count("mfa_missing") == 1
    assert (me["mfa_required"], me["mfa_passed"], me["mfa_enforced"]) == (True, False, False)


async def test_enforced_refuses_aal1_with_a_code_and_admits_aal2(supabase, monkeypatch):
    monkeypatch.setenv("MFA_ENFORCE", "1")
    sub = await _admin()
    async with _client() as client:
        refused = await client.get("/scheduled-jobs", headers=_h(sub, "aal1"))
        assert refused.status_code == 403 and refused.json()["code"] == "mfa_required"
        assert (await client.get("/admin/users", headers=_h(sub, "aal1"))).json()["code"] == "mfa_required"
        assert (await client.get("/scheduled-jobs", headers=_h(sub, "aal2"))).status_code == 200
        me = (await client.get("/auth/me", headers=_h(sub, "aal2"))).json()
        assert (me["mfa_passed"], me["mfa_enforced"]) == (True, True)
        # /auth/me itself never needs the second factor: the UI reads it to ask.
        assert (await client.get("/auth/me", headers=_h(sub, "aal1"))).status_code == 200


async def test_guardians_are_never_asked(supabase, monkeypatch):
    monkeypatch.setenv("MFA_ENFORCE", "1")
    sub = await _admin(super_admin=False)
    async with _client() as client:
        assert (await client.get("/students", headers=_h(sub, "aal1"))).status_code == 200
        me = (await client.get("/auth/me", headers=_h(sub, "aal1"))).json()
    assert me["mfa_required"] is False
