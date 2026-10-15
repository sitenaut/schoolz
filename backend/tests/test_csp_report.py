"""CSP violation reports (SZ-19): both wire formats are read, only origins
and paths are logged, and junk or floods are dropped quietly."""
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import json
import logging

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from routers import csp_report

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def _fresh_budget():
    csp_report._seen.clear()


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


def _logged(caplog):
    return [r for r in caplog.records if r.message == "csp_violation"]


async def test_report_uri_format_is_logged_without_queries(caplog):
    body = {"csp-report": {
        "document-uri": "https://schoolz.sitenaut.com/schools/x?token=secret",
        "effective-directive": "script-src-elem",
        "blocked-uri": "https://evil.example/x.js?k=v",
        "source-file": "https://schoolz.sitenaut.com/assets/index.js",
        "line-number": 12,
        "disposition": "report",
    }}
    async with _client() as client:
        with caplog.at_level(logging.INFO, logger="routers.csp_report"):
            res = await client.post("/csp-report", content=json.dumps(body), headers={"Content-Type": "application/csp-report"})
    assert res.status_code == 204
    (r,) = _logged(caplog)
    assert (r.directive, r.blocked, r.page, r.line) == ("script-src-elem", "https://evil.example", "/schools/x", 12)
    assert "secret" not in str(r.__dict__)


async def test_reporting_api_format_and_junk(caplog):
    batch = [
        {"type": "csp-violation", "body": {"effectiveDirective": "connect-src", "blockedURL": "https://stats.g.doubleclick.net/g/collect", "documentURL": "https://schoolz.sitenaut.com/"}},
        {"type": "deprecation", "body": {}},
        "not an object",
    ]
    async with _client() as client:
        with caplog.at_level(logging.INFO, logger="routers.csp_report"):
            ok = await client.post("/csp-report", content=json.dumps(batch), headers={"Content-Type": "application/reports+json"})
            junk = await client.post("/csp-report", content=b"{not json", headers={"Content-Type": "application/csp-report"})
            big = await client.post("/csp-report", content=b"x" * (csp_report._MAX_BODY + 1))
    assert ok.status_code == junk.status_code == big.status_code == 204
    (r,) = _logged(caplog)
    assert (r.directive, r.blocked, r.page) == ("connect-src", "https://stats.g.doubleclick.net", "/")


async def test_a_flood_is_dropped_past_the_budget(caplog, monkeypatch):
    monkeypatch.setattr(csp_report, "_BUDGET", 3)
    body = json.dumps({"csp-report": {"effective-directive": "img-src", "blocked-uri": "data"}})
    async with _client() as client:
        with caplog.at_level(logging.INFO, logger="routers.csp_report"):
            for _ in range(5):
                await client.post("/csp-report", content=body)
    assert len(_logged(caplog)) == 3
