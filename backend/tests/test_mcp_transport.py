"""The MCP endpoint answers on the API's real hostnames. mcp >= 1.2x checks
the Host header, and its default list is localhost only - which turned every
prod request into "421 Invalid Host header" after the SZ-22 upgrade."""

import httpx
import pytest
from fastapi import FastAPI

from mcp_server import build_mcp_server

_INIT = {
    "jsonrpc": "2.0",
    "id": 1,
    "method": "initialize",
    "params": {"protocolVersion": "2025-03-26", "capabilities": {}, "clientInfo": {"name": "test", "version": "0"}},
}
_HEADERS = {"Accept": "application/json, text/event-stream", "Content-Type": "application/json"}


async def _initialize(base_url: str, headers: dict | None = None) -> httpx.Response:
    mcp = build_mcp_server(FastAPI())
    app = mcp.streamable_http_app()
    async with mcp.session_manager.run():
        async with httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url=base_url) as client:
            return await client.post("/", json=_INIT, headers={**_HEADERS, **(headers or {})})


@pytest.mark.anyio
@pytest.mark.parametrize("base_url", ["https://schoolz-api.sitenaut.com", "https://schoolz-api.fly.dev", "http://localhost:8000"])
async def test_initialize_answers_on_the_apis_own_hostnames(base_url):
    res = await _initialize(base_url)
    assert res.status_code == 200, res.text
    assert '"protocolVersion"' in res.text


@pytest.mark.anyio
async def test_an_unknown_host_is_still_refused():
    res = await _initialize("https://rebound.example.com")
    assert res.status_code == 421


@pytest.mark.anyio
async def test_a_browser_origin_from_the_web_app_is_accepted():
    res = await _initialize("https://schoolz-api.sitenaut.com", {"Origin": "https://schoolz.sitenaut.com"})
    assert res.status_code == 200, res.text
