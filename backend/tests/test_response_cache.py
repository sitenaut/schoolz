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
async def test_an_entry_past_its_stale_window_is_recomputed_before_answering():
    clock = Clock()
    cache = SingleFlightTTLCache(ttl_s=60, stale_s=30, clock=clock)
    await cache.get_or_compute("k", _counting(b"old")[1])
    clock.now += 91
    calls, compute = _counting(b"new")
    assert await cache.get_or_compute("k", compute) == b"new"
    assert calls["n"] == 1


@pytest.mark.anyio
async def test_a_recently_expired_entry_is_served_at_once_and_refreshed_behind_it():
    clock = Clock()
    cache = SingleFlightTTLCache(ttl_s=60, stale_s=3600, clock=clock)
    await cache.get_or_compute("k", _counting(b"old")[1])
    clock.now += 61
    calls, compute = _counting(b"new")
    # Every caller until the refresh lands gets the old copy, and only one refresh runs.
    assert await asyncio.gather(*(cache.get_or_compute("k", compute) for _ in range(3))) == [b"old"] * 3
    await cache._inflight["k"]
    assert calls["n"] == 1
    assert await cache.get_or_compute("k", compute) == b"new"
    assert calls["n"] == 1  # fresh again: served without another computation


@pytest.mark.anyio
async def test_a_failed_background_refresh_keeps_the_old_copy_and_is_logged(caplog):
    clock = Clock()
    cache = SingleFlightTTLCache(ttl_s=60, clock=clock)
    await cache.get_or_compute("k", _counting(b"old")[1])
    clock.now += 61

    async def boom():
        raise RuntimeError("db down")

    assert await cache.get_or_compute("k", boom) == b"old"
    with pytest.raises(RuntimeError):
        await cache._inflight["k"]
    await asyncio.sleep(0)  # let the done-callback run
    assert "response_cache_refresh_failed" in caplog.text
    assert "k" not in cache._inflight
    assert await cache.get_or_compute("k", _counting(b"new")[1]) == b"old"  # and the next caller tries again


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
    cache = SingleFlightTTLCache(ttl_s=60, stale_s=0, clock=clock)
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

    async def grad_years(db, user_id):
        return {"u-2027": {2027}, "u-2027b": {2027}, "u-2030": {2030}}.get(user_id, set())

    monkeypatch.setattr(cal, "_list_calendar_items", fake_query)
    monkeypatch.setattr(cal, "_my_grad_years", grad_years)
    monkeypatch.setattr(cal.database, "SessionLocal", lambda: FakeSession())
    monkeypatch.setattr(cal, "_CACHE", SingleFlightTTLCache(ttl_s=60))
    return cal, calls


class _User:
    def __init__(self, user_id):
        self.id = user_id


async def _call(cal, query, *, user=None, q=None, school_ids=None, lang="en"):
    return await cal.list_calendar_items(
        request=_request(query), start=None, end=None, school_id=None, school_ids=school_ids, category=None,
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
async def test_searches_and_signed_in_views_naming_no_schools_are_never_shared(wired):
    cal, calls = wired
    user = _User("u-2027")
    await _call(cal, "start=a", user=user)
    await _call(cal, "start=a", user=user)
    await _call(cal, "start=a&q=lunch", q="lunch")
    await _call(cal, "start=a&q=lunch", q="lunch")
    assert len(calls) == 4
    assert calls[0]["user"] is user


@pytest.mark.anyio
async def test_a_signed_in_view_naming_its_schools_is_shared_by_grad_years(wired):
    cal, calls = wired
    query = "start=a&school_ids=east,west"
    await _call(cal, query, user=_User("u-2027"), school_ids="east,west")
    await _call(cal, "school_ids=west,east&start=a", user=_User("u-2027b"), school_ids="west,east")  # same years, other order
    await _call(cal, query, user=_User("u-2030"), school_ids="east,west")
    await _call(cal, query, user=_User("u-none"), school_ids="east,west")
    await _call(cal, query, school_ids="east,west")  # anonymous: no grad years, same as u-none
    assert [c["grad_years"] for c in calls] == [{2027}, {2030}, set()]
    assert all(c["user"] is None for c in calls)  # nothing else of theirs reaches the shared result


@pytest.mark.anyio
async def test_a_zero_ttl_runs_the_query_every_time_with_the_callers_own_session(wired, monkeypatch):
    cal, calls = wired
    monkeypatch.setattr(cal, "_CACHE", SingleFlightTTLCache(ttl_s=0))
    await _call(cal, "start=a")
    await _call(cal, "start=a")
    assert len(calls) == 2


def test_sizeof_is_what_the_byte_budget_counts():
    cache = SingleFlightTTLCache(ttl_s=60, max_total_bytes=25, max_entry_bytes=20, sizeof=lambda people: 10 * len(people))
    cache._store("a", ["p", "p"])
    cache._store("b", ["p"])
    assert cache._total_bytes == 30 - 20  # "a" (20) went first to fit "b" under 25
    cache._store("c", ["p", "p", "p"])  # 30 > the 20 a single entry may hold
    assert "c" not in cache._entries and cache._total_bytes == 10


# ---- the other cached routes, their DB work stubbed out ----


class _FakeSession:
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc):
        return False


@pytest.fixture
def no_db(monkeypatch):
    import database

    monkeypatch.setattr(database, "SessionLocal", lambda: _FakeSession())


@pytest.mark.anyio
async def test_directory_filters_one_cached_list_per_district_scope(monkeypatch, no_db):
    import routers.directory as d

    def person(pid, name, category, haystack):
        return d._Person(id=pid, full_name=name, title=None, role=None, department=None, email=None, phone=None,
                         category=category, schools=(), school_slugs=("s",), school_ids=("s1",), school_types=("high",),
                         affiliation="S", is_district_wide=False, haystack=haystack)

    people = [person("1", "Ann Lee", "nurse", "ann lee school nurse"), person("2", "Bo Diaz", "teacher", "bo diaz math")]
    calls = []

    async def fake(db, scope):
        calls.append(scope)
        return people

    monkeypatch.setattr(d, "_collapsed_people", fake)
    monkeypatch.setattr(d, "_PEOPLE", SingleFlightTTLCache(ttl_s=60, sizeof=len))

    async def search(**kw):
        args = {"q": None, "school_id": None, "school_type": None, "category": None, "district_id": [], "limit": 50, "offset": 0, "db": object()}
        return await d.search_directory(**(args | kw))

    assert (await search()).total == 2
    assert [p.full_name for p in (await search(q="nurse")).items] == ["Ann Lee"]
    assert (await search(category="teacher")).total == 1
    await search(district_id=["b", "a"])
    await search(district_id=["a", "b", "a"])
    assert calls == [(), ("a", "b")]  # one build per scope, whatever the order
    assert len(people) == 2  # filtering never changes the shared list


@pytest.mark.anyio
async def test_sitemap_audit_and_resource_counts_are_built_once_per_key(monkeypatch, no_db):
    import routers.data_audit as audit_router
    import routers.resources as resources
    import routers.seo as seo

    calls = []

    async def sitemap_xml(db):
        calls.append("sitemap")
        return b"<urlset/>"

    async def grid(db, aud, district_id, detail):
        calls.append(("audit", aud, district_id, detail))
        return {"schools": []}

    async def counts(db, county):
        calls.append(("categories", county))
        return [resources.CategoryOut(key="food", label="Food", count=3)]

    monkeypatch.setattr(seo, "_sitemap_xml", sitemap_xml)
    monkeypatch.setattr(seo, "_SITEMAP", SingleFlightTTLCache(ttl_s=60))
    monkeypatch.setattr(audit_router, "_grid", grid)
    monkeypatch.setattr(audit_router, "_PUBLIC_GRID", SingleFlightTTLCache(ttl_s=60))
    monkeypatch.setattr(resources, "_category_counts", counts)
    monkeypatch.setattr(resources, "_CATEGORY_COUNTS", SingleFlightTTLCache(ttl_s=60))

    for _ in range(2):
        assert (await seo.sitemap(db=object())).body == b"<urlset/>"
        assert (await audit_router.public_audit(district_id="d1", detail=False, db=object())).body == b'{"schools":[]}'
        assert (await resources.list_categories(county="Camden", db=object())).body == b'[{"key":"food","label":"Food","count":3}]'
    await audit_router.public_audit(district_id="d1", detail=True, db=object())
    await resources.list_categories(county=None, db=object())
    assert calls == ["sitemap", ("audit", "district", "d1", False), ("categories", "Camden"), ("audit", "district", "d1", True), ("categories", None)]
