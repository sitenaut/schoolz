"""The Gmail connect state (SZ-10): signed with its own key, carries a
purpose, and works once. Prod once signed it with an empty JWT_SECRET, so a
state forged with "" is the first thing checked."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import base64
import hashlib
import hmac
import json
from datetime import datetime, timedelta, timezone
from urllib.parse import parse_qs, urlparse

import jwt
import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from main import app
from models import GmailToken
from routers import gmail
from tests.test_admin_users import _register

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _google(monkeypatch):
    monkeypatch.setenv("DATA_ENCRYPTION_KEYS", Fernet.generate_key().decode())
    monkeypatch.setenv("PUBLIC_API_URL", "http://test")
    monkeypatch.setattr(gmail, "GOOGLE_CLIENT_ID", "client-id")
    monkeypatch.setattr(gmail, "GOOGLE_CLIENT_SECRET", "client-secret")

    class FakeGoogle:
        def __init__(self, *a, **kw):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

        async def post(self, url, data):
            class R:
                status_code = 200

                def json(self):
                    return {"access_token": "ya29.a", "refresh_token": "1//r", "expires_in": 3600}

            return R()

        async def get(self, url, headers):
            class R:
                status_code = 200

                def json(self):
                    return {"email": "inbox@example.com"}

            return R()

    monkeypatch.setattr(gmail.httpx, "AsyncClient", FakeGoogle)


def _sign_with_empty_key(claims: dict) -> str:
    """What prod's state looked like (JWT_SECRET unset); PyJWT now refuses
    to make one, so it is put together by hand."""
    b64 = lambda raw: base64.urlsafe_b64encode(raw).rstrip(b"=")  # noqa: E731
    signing_input = b64(json.dumps({"alg": "HS256", "typ": "JWT"}).encode()) + b"." + b64(json.dumps(claims).encode())
    return (signing_input + b"." + b64(hmac.new(b"", signing_input, hashlib.sha256).digest())).decode()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _state(client: AsyncClient, headers: dict) -> str:
    res = await client.get("/gmail/auth-url", headers=headers)
    assert res.status_code == 200, res.text
    return parse_qs(urlparse(res.json()["url"]).query)["state"][0]


async def test_a_state_connects_once():
    async with _client() as client:
        admin, admin_id = await _register(client, "gmailstate", super_admin=True)
        state = await _state(client, admin)

        first = await client.get("/gmail/callback", params={"code": "c", "state": state})
        assert "gmail:connected" in first.text
        again = await client.get("/gmail/callback", params={"code": "c", "state": state})
        assert "gmail:error" in again.text

    async with database.SessionLocal() as db:
        row = (await db.execute(select(GmailToken).where(GmailToken.user_id == admin_id))).scalar_one()
        assert row.google_email == "inbox@example.com"


async def test_forged_and_misused_states_are_refused():
    async with _client() as client:
        admin, admin_id = await _register(client, "gmailforge", super_admin=True)
        real = jwt.decode(await _state(client, admin), options={"verify_signature": False})
        exp = datetime.now(timezone.utc) + timedelta(minutes=5)

        forged_empty = _sign_with_empty_key({**real, "exp": int(exp.timestamp())})
        forged_jwt_secret = jwt.encode({**real, "exp": exp}, "test-secret", algorithm="HS256")
        for state in (forged_empty, forged_jwt_secret, "not-a-jwt"):
            res = await client.get("/gmail/callback", params={"code": "c", "state": state})
            assert "gmail:error" in res.text

        # Right key, wrong purpose.
        key = gmail._state_key()
        other = jwt.encode({**real, "purpose": "something-else", "exp": exp}, key, algorithm="HS256")
        assert "gmail:error" in (await client.get("/gmail/callback", params={"code": "c", "state": other})).text

        # Right key and purpose, but a nonce that was never handed out.
        unknown = jwt.encode({**real, "jti": "never-issued", "exp": exp}, key, algorithm="HS256")
        assert "gmail:error" in (await client.get("/gmail/callback", params={"code": "c", "state": unknown})).text

        # The real state was not used up by any of that.
        good = jwt.encode({**real, "exp": exp}, key, algorithm="HS256")
        assert "gmail:connected" in (await client.get("/gmail/callback", params={"code": "c", "state": good})).text


async def test_no_key_when_deployed_means_not_configured(monkeypatch):
    monkeypatch.delenv("DATA_ENCRYPTION_KEYS")
    monkeypatch.setenv("FLY_MACHINE_ID", "test-machine")
    async with _client() as client:
        admin, _ = await _register(client, "gmailnokey", super_admin=True)
        assert (await client.get("/gmail/auth-url", headers=admin)).status_code == 503
