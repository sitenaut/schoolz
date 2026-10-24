"""Supabase token checks (SZ-12): only an unreachable key set falls back to
asking Supabase; an expired or forged token, or one naming a key the set
doesn't have, is a 401 on the spot, without a round trip."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import jwt
import pytest
from fastapi import HTTPException

import auth

pytestmark = pytest.mark.anyio


class _Key:
    key = "k"


class _Jwks:
    def __init__(self, error: Exception | None = None):
        self.error = error

    def get_signing_key_from_jwt(self, token):
        if self.error:
            raise self.error
        return _Key()


@pytest.fixture
def fallback_calls(monkeypatch):
    calls = []

    async def fake(token):
        calls.append(token)
        return {"sub": "from-supabase"}

    monkeypatch.setattr(auth, "_supabase_user", fake)
    return calls


async def test_an_unreachable_key_set_asks_supabase(monkeypatch, fallback_calls):
    monkeypatch.setattr(auth, "_jwks_client", _Jwks(jwt.PyJWKClientConnectionError("timed out")))
    assert await auth._verify_supabase_token("t") == {"sub": "from-supabase"}
    assert fallback_calls == ["t"]


async def test_an_unknown_signing_key_is_refused_locally(monkeypatch, fallback_calls):
    monkeypatch.setattr(auth, "_jwks_client", _Jwks(jwt.PyJWKClientError('Unable to find a signing key that matches: "x"')))
    with pytest.raises(HTTPException) as err:
        await auth._verify_supabase_token("t")
    assert err.value.status_code == 401
    assert fallback_calls == []


async def test_expired_or_garbage_tokens_are_refused_locally(monkeypatch, fallback_calls):
    monkeypatch.setattr(auth, "_jwks_client", _Jwks())

    def expired(*a, **kw):
        raise jwt.ExpiredSignatureError("expired")

    monkeypatch.setattr(auth.jwt, "decode", expired)
    with pytest.raises(HTTPException) as err:
        await auth._verify_supabase_token("t")
    assert err.value.status_code == 401

    monkeypatch.setattr(auth, "_jwks_client", _Jwks(jwt.DecodeError("not a jwt")))
    with pytest.raises(HTTPException):
        await auth._verify_supabase_token("garbage")
    assert fallback_calls == []
