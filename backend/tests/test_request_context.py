"""Request IDs and the error envelope (SZ-17)."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import logging

import pytest
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient

import request_context
from main import app
from request_context import RequestIdLogFilter, request_id_var

pytestmark = pytest.mark.anyio

# Its own app, so the real one's route list (and its gate snapshot) is untouched.
_boom_app = FastAPI()
request_context.install(_boom_app)


@_boom_app.get("/boom")
async def boom():
    raise RuntimeError("secret internals")


def _client(target=app, **kw) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=target, **kw), base_url="http://test")


async def test_every_response_carries_an_id_and_a_sane_one_is_kept():
    async with _client() as client:
        fresh = await client.get("/health")
        assert len(fresh.headers["x-request-id"]) == 32
        kept = await client.get("/health", headers={"X-Request-ID": "trace-abc-12345"})
        assert kept.headers["x-request-id"] == "trace-abc-12345"
        # Anything odd (spaces, too short, too long) is replaced, never echoed.
        for junk in ("short", "has spaces in it ok", "x" * 65, "semi;colon;value"):
            res = await client.get("/health", headers={"X-Request-ID": junk})
            assert res.headers["x-request-id"] != junk


async def test_http_errors_keep_detail_and_add_code_and_id():
    async with _client() as client:
        res = await client.get("/auth/me")
        assert res.status_code == 401
        body = res.json()
        assert body["detail"] == "Not authenticated"
        assert body["code"] == "unauthorized"
        assert body["request_id"] == res.headers["x-request-id"]

        missing = await client.get("/no-such-route")
        assert missing.json()["code"] == "not_found"


async def test_validation_errors_keep_fastapis_list():
    async with _client() as client:
        res = await client.post("/auth/login", json={})
        assert res.status_code == 422
        body = res.json()
        assert isinstance(body["detail"], list) and body["detail"][0]["type"] == "missing"
        assert body["code"] == "validation_error" and body["request_id"]


async def test_unhandled_errors_hide_the_exception_and_log_it_under_the_id(caplog):
    async with _client(_boom_app, raise_app_exceptions=False) as client:
        with caplog.at_level(logging.ERROR, logger="request_context"):
            res = await client.get("/boom", headers={"X-Request-ID": "boom-req-0001"})
    assert res.status_code == 500
    assert res.json() == {"detail": "Internal server error", "code": "internal_error", "request_id": "boom-req-0001"}
    assert "secret internals" not in res.text
    logged = [r for r in caplog.records if r.message == "unhandled_error"]
    assert logged and logged[0].request_id == "boom-req-0001"


def test_log_lines_get_the_current_request_id():
    record = logging.LogRecord("x", logging.INFO, __file__, 1, "m", None, None)
    token = request_id_var.set("req-in-context-1")
    try:
        RequestIdLogFilter().filter(record)
    finally:
        request_id_var.reset(token)
    assert record.request_id == "req-in-context-1"
