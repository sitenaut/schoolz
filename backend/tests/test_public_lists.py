"""The lists every page asks for are cached for anonymous visitors, and a
full database pool answers "busy" at once (services/public_lists.py,
request_context._pool_busy).

A crawler rendering about 2,000 pages filled both API machines' pools on
2026-11-25: /schools, /districts/summary and /seasonal-guides, each asked
for by every page and none cached, took the largest share of request time,
and every route then waited 30 seconds for a connection and answered 500."""
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy.exc import TimeoutError as PoolTimeout

import database
import main
from models import District, School
from services import public_lists
from services.response_cache import SingleFlightTTLCache

pytestmark = pytest.mark.anyio


@pytest.fixture
async def client():
    async with AsyncClient(transport=ASGITransport(app=main.app), base_url="http://test") as c:
        yield c


@pytest.fixture
def cache_on(monkeypatch):
    monkeypatch.setattr(public_lists, "CACHE", SingleFlightTTLCache(ttl_s=60))


async def _add_school(name: str) -> None:
    async with database.SessionLocal() as db:
        district = District(name=f"{name} District")
        db.add(district)
        await db.flush()
        db.add(School(name=name, slug=name.lower().replace(" ", "-"), district_id=district.id, school_type="elementary"))
        await db.commit()


def _names(res) -> set[str]:
    return {row["name"] for row in res.json()}


async def test_an_anonymous_visitor_gets_the_stored_list_and_a_signed_in_one_the_database(client, cache_on):
    await _add_school("Cached List Elementary")
    first = await client.get("/schools")
    assert first.status_code == 200 and "Cached List Elementary" in _names(first)
    assert first.headers["content-type"].startswith("application/json")

    await _add_school("Added Later Elementary")
    assert "Added Later Elementary" not in _names(await client.get("/schools"))
    # Anything carrying a sign-in or an API key reads the database: an admin
    # who edits a school sees it in the list at once.
    assert "Added Later Elementary" in _names(await client.get("/schools", headers={"Authorization": "Bearer not-a-token"}))


async def test_district_summaries_and_seasonal_guides_are_stored_too(client, cache_on):
    await _add_school("Summary One Elementary")
    assert "Summary One Elementary District" in _names(await client.get("/districts/summary"))
    await _add_school("Summary Two Elementary")
    assert "Summary Two Elementary District" not in _names(await client.get("/districts/summary"))

    assert (await client.get("/seasonal-guides")).status_code == 200
    assert (await client.get("/seasonal-guides")).json() == (await client.get("/seasonal-guides", headers={"Authorization": "Bearer x"})).json()


async def test_with_the_cache_off_every_request_reads_the_database(client):
    assert not public_lists.CACHE.enabled  # conftest turns it off for the suite
    await _add_school("Uncached One Elementary")
    await client.get("/schools")
    await _add_school("Uncached Two Elementary")
    assert "Uncached Two Elementary" in _names(await client.get("/schools"))


async def test_a_full_pool_answers_busy_with_a_retry_hint_not_a_500(client):
    from database import get_db

    async def no_connection():
        raise PoolTimeout("QueuePool limit of size 3 overflow 1 reached, connection timed out, timeout 5.00")
        yield  # pragma: no cover - makes this a generator dependency

    main.app.dependency_overrides[get_db] = no_connection
    try:
        res = await client.get("/schools")
    finally:
        main.app.dependency_overrides.pop(get_db, None)
    assert res.status_code == 503
    assert res.headers["Retry-After"] == "2"
    assert "busy" in res.json()["detail"]


def test_the_api_gives_up_on_a_connection_quickly():
    assert database.engine.pool.timeout() == 5
