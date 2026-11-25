"""The latency SLO's own measurement (main.record_interactive_get).

The nightly prerender warm-up renders 2,000+ pages, each making the API calls
a visitor's page makes; counted as visitors they burned the latency budget
every night (2026-11-25). The frontend marks calls made during a render and
the API records them apart."""
import pytest
from httpx import ASGITransport, AsyncClient

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
