"""The latency SLO's own measurement (main.record_interactive_get).

The nightly prerender warm-up renders 2,000+ pages, each making the API calls
a visitor's page makes; counted as visitors they burned the latency budget
every night (2026-11-25). The frontend marks calls made during a render and
the API records them apart."""
import logging

import pytest
from httpx import ASGITransport, AsyncClient
from starlette.requests import Request

import main
import observability

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        yield c


@pytest.fixture
def recorded(monkeypatch):
    seen: list[tuple[float, dict]] = []

    class Spy:
        def record(self, value, attributes=None):
            seen.append((value, attributes))

    monkeypatch.setattr(observability, "interactive_get_seconds", Spy())
    return seen


async def test_a_visitors_get_and_a_render_s_get_are_recorded_apart(client, recorded):
    await client.get("/schools")
    await client.get("/schools", headers={main.AUTOMATED_HEADER: "1"})

    assert [attrs for _, attrs in recorded] == [{"traffic": "visitor"}, {"traffic": "automated"}]
    assert all(seconds >= 0 for seconds, _ in recorded)


async def test_routes_the_slo_leaves_out_and_other_methods_are_not_recorded(client, recorded):
    await client.get("/admin/config/results")  # 401, an admin route
    await client.get("/prerender", params={"path": "/nope"})
    await client.post("/chat", json={})
    assert recorded == []

    # No route matched: counted, as the request histogram counts it.
    await client.get("/no-such-page")
    assert [attrs for _, attrs in recorded] == [{"traffic": "visitor"}]


async def test_routes_only_programs_ask_for_count_as_automated(client, recorded):
    # Search engines' sitemap fetches and a connected app's hourly family
    # feed poll were half the "visitor" requests over a second (2026-11-26).
    await client.get("/sitemap.xml")
    await client.get("/family/feed")  # 401 without a key, still that route
    assert [attrs for _, attrs in recorded] == [{"traffic": "automated"}, {"traffic": "automated"}]


async def test_every_request_log_line_says_whether_a_person_was_waiting(client, caplog):
    # The logs once held a day of slow requests nobody could sort into
    # visitors and crawlers (2026-11-26).
    with caplog.at_level(logging.INFO, logger="main"):
        await client.get("/schools")
        await client.get("/schools", headers={main.AUTOMATED_HEADER: "1"})
        await client.get("/sitemap.xml")
        await client.post("/chat", json={})  # not a GET, still a person
    lines = [r for r in caplog.records if r.getMessage() == "http_request"]
    assert [(r.route, r.traffic) for r in lines] == [
        ("/schools", "visitor"), ("/schools", "automated"), ("/sitemap.xml", "automated"), ("/chat", "visitor"),
    ]


def test_a_script_holding_an_api_key_is_automated():
    request = Request({"type": "http", "method": "GET", "path": "/schools", "headers": [], "state": {"api_key_id": "k1"}})
    assert main.request_traffic(request, "/schools") == "automated"
    request = Request({"type": "http", "method": "GET", "path": "/schools", "headers": [], "state": {}})
    assert main.request_traffic(request, "/schools") == "visitor"
