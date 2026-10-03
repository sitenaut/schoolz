import asyncio

import pytest
from starlette.requests import Request

from services.response_cache import SingleFlightTTLCache


class Clock:
    def __init__(self):
        self.now = 1000.0

    def __call__(self):
        return self.now


def _counting(body=b"x"):
    calls = {"n": 0}

    async def compute():
        calls["n"] += 1
        await asyncio.sleep(0)
        return body

    return calls, compute


@pytest.mark.anyio
async def test_a_fresh_entry_is_served_without_recomputing():
    clock = Clock()
    cache = SingleFlightTTLCache(ttl_s=60, clock=clock)
    calls, compute = _counting(b"a")
    assert await cache.get_or_compute("k", compute) == b"a"
    clock.now += 59
    assert await cache.get_or_compute("k", compute) == b"a"
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_an_expired_entry_is_recomputed():
    clock = Clock()
    cache = SingleFlightTTLCache(ttl_s=60, clock=clock)
    calls, compute = _counting()
    await cache.get_or_compute("k", compute)
    clock.now += 61
    await cache.get_or_compute("k", compute)
    assert calls["n"] == 2


@pytest.mark.anyio
async def test_concurrent_identical_requests_share_one_computation():
    cache = SingleFlightTTLCache(ttl_s=60)
    calls, compute = _counting(b"shared")
    results = await asyncio.gather(*(cache.get_or_compute("k", compute) for _ in range(8)))
    assert results == [b"shared"] * 8
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_a_failure_is_not_cached_and_reaches_every_waiter():
    cache = SingleFlightTTLCache(ttl_s=60)
    calls = {"n": 0}

    async def boom():
        calls["n"] += 1
        await asyncio.sleep(0)
        raise RuntimeError("db down")

    results = await asyncio.gather(*(cache.get_or_compute("k", boom) for _ in range(3)), return_exceptions=True)
    assert all(isinstance(r, RuntimeError) for r in results)
    assert calls["n"] == 1
    _, ok = _counting(b"recovered")
    assert await cache.get_or_compute("k", ok) == b"recovered"


@pytest.mark.anyio
async def test_stale_data_is_served_when_the_refresh_fails():
    clock = Clock()
    cache = SingleFlightTTLCache(ttl_s=60, clock=clock)
    _, compute = _counting(b"old")
    await cache.get_or_compute("k", compute)
    clock.now += 120

    async def boom():
        raise RuntimeError("db down")

    assert await cache.get_or_compute("k", boom) == b"old"


@pytest.mark.anyio
async def test_an_oversized_body_is_returned_but_not_held():
    cache = SingleFlightTTLCache(ttl_s=60, max_entry_bytes=10)
    calls, compute = _counting(b"x" * 11)
    assert await cache.get_or_compute("k", compute) == b"x" * 11
    await cache.get_or_compute("k", compute)
    assert calls["n"] == 2


@pytest.mark.anyio
async def test_the_oldest_entries_are_evicted_past_the_byte_budget():
    cache = SingleFlightTTLCache(ttl_s=60, max_total_bytes=25, max_entry_bytes=10)
    for key in ("a", "b", "c"):
        _, compute = _counting(b"x" * 10)
        await cache.get_or_compute(key, compute)
    assert cache._total_bytes <= 25
    assert "a" not in cache._entries and "c" in cache._entries


def test_a_zero_ttl_disables_the_cache():
    assert not SingleFlightTTLCache(ttl_s=0).enabled


# ---- the /calendar wiring, with the DB-backed query stubbed out ----


def _request(query: str) -> Request:
    return Request({"type": "http", "method": "GET", "path": "/calendar", "query_string": query.encode(), "headers": []})


@pytest.fixture
def wired(monkeypatch):
    import routers.calendar as cal

    calls = []

    async def fake_query(**kw):
        calls.append(kw)
        return []

    class FakeSession:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *exc):
            return False

    monkeypatch.setattr(cal, "_list_calendar_items", fake_query)
    monkeypatch.setattr(cal.database, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cal, "_CACHE", SingleFlightTTLCache(ttl_s=60))
    return cal, calls


async def _call(cal, query, *, user=None, q=None, lang="en"):
    return await cal.list_calendar_items(
        request=_request(query), start=None, end=None, school_id=None, school_ids=None, category=None,
        q=q, include_class_sources=False, include_athletics=False, user=user, db=object(), lang=lang,
    )


@pytest.mark.anyio
async def test_anonymous_requests_for_one_window_share_a_result_whatever_the_param_order(wired):
    cal, calls = wired
    first = await _call(cal, "start=a&end=b")
    second = await _call(cal, "end=b&start=a")
    assert first.body == second.body == b"[]"
    assert len(calls) == 1


@pytest.mark.anyio
async def test_different_windows_and_languages_are_cached_separately(wired):
    cal, calls = wired
    await _call(cal, "start=a")
    await _call(cal, "start=b")
    await _call(cal, "start=a", lang="es")
    assert len(calls) == 3


@pytest.mark.anyio
async def test_signed_in_and_search_requests_are_never_shared(wired):
    cal, calls = wired
    user = object()
    await _call(cal, "start=a", user=user)
    await _call(cal, "start=a", user=user)
    await _call(cal, "start=a&q=lunch", q="lunch")
    await _call(cal, "start=a&q=lunch", q="lunch")
    assert len(calls) == 4
    assert calls[0]["user"] is user


@pytest.mark.anyio
async def test_a_zero_ttl_runs_the_query_every_time_with_the_callers_own_session(wired, monkeypatch):
    cal, calls = wired
    monkeypatch.setattr(cal, "_CACHE", SingleFlightTTLCache(ttl_s=0))
    await _call(cal, "start=a")
    await _call(cal, "start=a")
    assert len(calls) == 2
