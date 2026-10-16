import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import ResourceService
from resources import nj211
from resources.categories import categories_for_code, categories_for_codes
from resources.refresh import _rotated, missing_core, refresh_nj211
from scheduler.errors import parse_warning
from scheduler.jobs import resources_refresh

FIXTURES = Path(__file__).parent / "fixtures"
LISTING = (FIXTURES / "nj211_search_food_pantries.html").read_text(encoding="utf-8")
DETAIL = (FIXTURES / "nj211_service_detail.html").read_text(encoding="utf-8")
DETAIL_ID = "7fa184cb-8cb0-5194-8ee5-c83db87fe73f"
PLACE = {"label": "Cherry Hill, NJ", "county": "Camden", "lat": 39.9348, "lon": -75.0246}
BERGEN = {"label": "Hackensack, NJ", "county": "Bergen", "lat": 40.8859, "lon": -74.0435}


# ---- parsing ----------------------------------------------------------------


def test_search_page_joins_payload_chunks_and_reads_results():
    results, total = nj211.parse_search_page(LISTING)
    assert total == 49
    assert [r["name"] for r in results] == [
        "Food Pantry | Cherry Hill Seventh-Day Adventist Church",
        "Food Pantry | Cherry Hill Food Pantry",
        "Food Pantry | Gates of Praise Church of God",
    ]


def test_listing_fields_are_cleaned():
    first = nj211.parse_search_page(LISTING)[0][0]
    fields = nj211.summary_fields(first)
    assert fields["name"] == "Food Pantry"
    assert fields["organization_name"] == "Cherry Hill Seventh-Day Adventist Church"
    assert fields["address"] == "700 Cooper Landing Rd, Cherry Hill, NJ 08002"  # no-break spaces gone
    assert fields["description"] == "Provides food assistance for individuals in need."  # HTML stripped
    assert (fields["latitude"], fields["longitude"]) == (39.93187, -75.011891)
    assert fields["taxonomy_codes"] == ["BD-1800.2000"]
    assert fields["hours_text"] == "2nd Wed of the month 8:30 am - 12:30 pm"


def test_detail_page_fields():
    record = nj211.parse_detail_page(DETAIL, DETAIL_ID)
    fields = nj211.detail_fields(record)
    assert fields["name"] == "Betsy and Peter Fischer Food Pantry"
    assert fields["organization_name"] == "Jewish Family and Children's Services (JFCS) - Southern New Jersey"
    assert fields["phone"] == "856-424-1333"  # the voice line, not the fax
    assert (fields["address"], fields["city"], fields["postal_code"]) == ("6 E Miami Ave", "Cherry Hill", "08034")
    assert fields["service_areas"] == ["Burlington County, NJ", "Camden County, NJ", "Gloucester County, NJ"]
    assert fields["last_assured_on"] == date(2026, 2, 27)
    assert fields["required_documents"] == ["ID, proof of address"]
    assert set(fields["taxonomy_codes"]) == {"BM-6500.6500-650", "BD-1800.2000"}
    raw = nj211.storable_raw(record)
    assert "serviceArea" not in raw and "contacts" not in raw


def test_layout_changes_raise_instead_of_returning_nothing():
    with pytest.raises(ValueError):
        nj211.parse_search_page("<html><body>redesigned</body></html>")
    with pytest.raises(ValueError):
        nj211.parse_search_page('<script>self.__next_f.push([1,"0:{\\"P\\":null}"])</script>')
    with pytest.raises(ValueError):
        nj211.parse_detail_page(DETAIL, "00000000-0000-0000-0000-000000000000")


def test_an_empty_search_is_zero_not_an_error():
    page = '<script>self.__next_f.push([1,"{\\"results\\":[],\\"totalResults\\":0}"])</script>'
    assert nj211.parse_search_page(page) == ([], 0)


def test_taxonomy_codes_map_by_longest_prefix():
    assert categories_for_code("BD-1800.2000") == ("food",)
    assert categories_for_code("NL-3000.1500") == ("money-work", "kids-family")
    assert categories_for_code("BM-6500.1500-150") == ("everyday-needs", "kids-family")
    assert categories_for_code("BM-6500.6500-650") == ("everyday-needs",)
    assert categories_for_code("YZ-1470") == ()
    # Nav order, no duplicates.
    assert categories_for_codes(["NL-3000.1500", "BD-1800.2000", "PH-2400.1500"]) == ["food", "kids-family", "money-work"]


def test_missing_core_counts_service_areas_as_an_address():
    row = ResourceService(name="Hotline", phone="211", hours_text="24/7", taxonomy_codes=["RP-1500"], service_areas=["NJ"])
    assert missing_core(row) == []
    row = ResourceService(name="Pantry", taxonomy_codes=[], service_areas=[])
    assert missing_core(row) == ["address", "hours", "phone", "services"]


# ---- the polite client ---------------------------------------------------------


class _Clock:
    def __init__(self):
        self.now = 0.0
        self.slept: list[float] = []

    def __call__(self):
        return self.now

    async def sleep(self, seconds):
        self.slept.append(round(seconds, 3))
        self.now += seconds


def _client(handler, clock=None, delay=10.0):
    clock = clock or _Clock()
    http = httpx.AsyncClient(transport=httpx.MockTransport(handler), base_url=nj211.BASE_URL)
    return nj211.NJ211Client(delay_seconds=delay, http=http, sleep=clock.sleep, clock=clock), clock


ROBOTS = "User-Agent: SemrushBot\nDisallow: /\n\nUser-Agent: *\nAllow: /\nDisallow: /api/\nDisallow: /admin/\nCrawl-delay: 15\n"


@pytest.mark.anyio
async def test_requests_are_spaced_by_the_larger_of_our_delay_and_crawl_delay():
    seen = []

    def handler(request):
        seen.append(request)
        if request.url.path == "/robots.txt":
            return httpx.Response(200, text=ROBOTS)
        return httpx.Response(200, text=LISTING)

    client, clock = _client(handler, delay=3)
    assert client.delay == nj211.MIN_DELAY_SECONDS  # never below 10 s
    await client.check_robots()
    assert client.delay == 15
    await client.search("BD", PLACE)
    await client.search("BD", PLACE, page=2)
    assert clock.slept == [15, 15]
    assert seen[1].url.params["coords"] == "-75.0246,39.9348" and "page" not in seen[1].url.params
    assert seen[2].url.params["page"] == "2"
    assert seen[1].headers["user-agent"] == nj211.USER_AGENT


@pytest.mark.anyio
async def test_robots_disallowing_search_blocks_the_run():
    def handler(request):
        return httpx.Response(200, text="User-Agent: *\nDisallow: /search\n")

    client, _ = _client(handler)
    with pytest.raises(nj211.Blocked):
        await client.check_robots()


@pytest.mark.anyio
async def test_a_refusal_stops_rather_than_retrying():
    calls = []

    def handler(request):
        calls.append(request)
        return httpx.Response(429)

    client, _ = _client(handler)
    with pytest.raises(nj211.Blocked):
        await client.search("B", PLACE)
    assert len(calls) == 1


@pytest.mark.anyio
async def test_the_client_never_requests_the_api_or_odd_ids():
    client, _ = _client(lambda r: httpx.Response(200))
    with pytest.raises(ValueError):
        await client._get("/api/search")
    with pytest.raises(ValueError):
        await client.detail("../admin")


# ---- pipeline -----------------------------------------------------------------


def _listing(record_id, name="Food Pantry", org="Test Org", hours="Mon 9-5", code="BD-1800.2000"):
    return {
        "id": record_id,
        "serviceName": name,
        "name": f"{name} | {org}",
        "locationName": org,
        "description": "<p>Food.</p>",
        "phone": "856-555-0100",
        "address": "1 Main St, Cherry Hill, NJ 08002",
        "location": {"coordinates": [-75.0, 39.9], "type": "Point"},
        "taxonomies": [{"code": code, "name": "Food Pantries"}],
        "eligibility": "Open to anyone",
        "hours": hours,
    }


def _detail(record_id, org="Test Org"):
    return {
        "id": record_id,
        "serviceName": "Food Pantry",
        "name": f"Food Pantry | {org}",
        "organizationName": org,
        "phoneNumbers": [{"number": "856-555-0100", "type": "voice", "rank": 0}],
        "addresses": [{"address_1": "1 Main St", "city": "Cherry Hill", "postalCode": "08002", "type": "physical", "rank": 1}],
        "hours": "Mon 9-5",
        "categories": [{"code": "BD-1800.2000", "name": "Food Pantries"}],
        "serviceAreaName": "Camden County, NJ",
        "lastAssuredOn": "09/08/2025",
        "contacts": [{"name": "A Person", "email": "person@example.com"}],
    }


class FakeNJ211:
    def __init__(self, listings, block_after=None):
        self.listings = listings  # code -> list of results
        self.block_after = block_after
        self.requests = 0
        self.detail_ids: list[str] = []

    async def check_robots(self):
        pass

    async def search(self, code, place, page=1):
        self.requests += 1
        if self.block_after is not None and self.requests > self.block_after:
            raise nj211.Blocked("NJ 211 answered 403")
        results = self.listings.get(code, [])
        return results[(page - 1) * 25 : page * 25], len(results)

    async def detail(self, record_id):
        self.detail_ids.append(record_id)
        return _detail(record_id)


@pytest.fixture
async def only_test_records():
    """Set aside real crawled records (a local crawl leaves thousands) for
    the length of one test - the transaction is rolled back after - so the
    crawl's queue and its missing-record sweep see only this test's rows."""
    async with database.SessionLocal() as db:
        await db.execute(update(ResourceService).where(ResourceService.source == nj211.SOURCE).values(source="set-aside"))
        await db.commit()


def _cfg(**kw):
    return {"places": [PLACE], "taxonomy_roots": ["B", "L"], "force_list": True, "max_details_per_run": 500, **kw}


async def _rows(ids):
    async with database.SessionLocal() as db:
        rows = (await db.execute(select(ResourceService).where(ResourceService.source_record_id.in_(ids)))).scalars().all()
        return {r.source_record_id: r for r in rows}


@pytest.mark.anyio
async def test_first_run_inserts_listings_then_fetches_their_details(only_test_records):
    ids = [f"t-{uuid.uuid4()}" for _ in range(30)]  # more than one page
    fake = FakeNJ211({"B": [_listing(i) for i in ids]})
    async with database.SessionLocal() as db:
        summary = await refresh_nj211(db, _cfg(), client=fake)
    assert summary["list_crawl"] == "complete" and summary["new"] == 30 and summary["pages"] == 3  # B p1, B p2, L
    assert set(ids) <= set(fake.detail_ids)
    rows = await _rows(ids)
    row = rows[ids[0]]
    assert row.organization_name == "Test Org" and row.organization_id
    assert row.categories == ["food"] and row.missing_core == []
    assert row.city == "Cherry Hill" and row.service_areas == ["Camden County, NJ"]
    assert row.detail_fetched_at is not None and row.last_assured_on == date(2025, 9, 8)
    assert "contacts" not in row.raw  # staff names are never stored
    # One organization row, however many services it runs.
    assert len({r.organization_id for r in rows.values()}) == 1


@pytest.mark.anyio
async def test_a_changed_listing_requeues_its_detail_and_an_unchanged_one_does_not(only_test_records):
    a, b = f"t-{uuid.uuid4()}", f"t-{uuid.uuid4()}"
    async with database.SessionLocal() as db:
        await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(a), _listing(b)]}))
        fake = FakeNJ211({"B": [_listing(a, hours="Tue 10-2"), _listing(b)]})
        summary = await refresh_nj211(db, _cfg(), client=fake)
    assert summary["changed"] == 1 and summary["new"] == 0
    assert a in fake.detail_ids and b not in fake.detail_ids


@pytest.mark.anyio
async def test_records_go_inactive_after_two_complete_crawls_without_them(only_test_records):
    keep, gone = f"t-{uuid.uuid4()}", f"t-{uuid.uuid4()}"
    async with database.SessionLocal() as db:
        await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(keep), _listing(gone)]}))
        await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(keep)]}))
        assert (await _rows([gone]))[gone].status == "active"  # one miss isn't enough
        await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(keep)]}))
        rows = await _rows([keep, gone])
        assert rows[gone].status == "inactive" and rows[keep].status == "active"
        # Back in the listing: active again.
        summary = await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(keep), _listing(gone)]}))
    assert summary["reactivated"] == 1
    assert (await _rows([gone]))[gone].status == "active"


@pytest.mark.anyio
async def test_a_blocked_crawl_keeps_what_it_saved_and_deactivates_nothing(only_test_records):
    first, second = f"t-{uuid.uuid4()}", f"t-{uuid.uuid4()}"
    async with database.SessionLocal() as db:
        await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(first)], "L": [_listing(second, code="LN-1500")]}))
        for _ in range(3):
            # B answers, then L is refused: a partial crawl must never count
            # `second` as missing.
            summary = await refresh_nj211(db, _cfg(), client=FakeNJ211({"B": [_listing(first)]}, block_after=1))
    assert summary["blocked"] and summary["list_crawl"] == "partial"
    assert (await _rows([second]))[second].status == "active"


@pytest.mark.anyio
async def test_job_reports_blocks_and_partial_runs_as_coded_warnings(monkeypatch):
    base = {"list_crawl": "complete", "listed": 5, "errors": [], "detail_failures": 0, "blocked": None}

    def returning(summary):
        async def fake(db, cfg):
            return summary

        return fake

    for outcome, code in [
        ({"blocked": "NJ 211 answered 403"}, "resource_source_blocked"),
        ({"errors": ["Cherry Hill B p2: timeout"]}, "resource_source_partial"),
        ({"listed": 0}, "resource_source_empty"),
        ({}, None),
    ]:
        monkeypatch.setattr(resources_refresh, "refresh_nj211", returning(dict(base, **outcome)))
        assert parse_warning(await resources_refresh.run(None, {"nj211": {"places": [PLACE]}})) == code
    assert parse_warning(await resources_refresh.run(None, {})) == "resources_no_sources"


# ---- API ------------------------------------------------------------------------


async def _seed(**overrides):
    fields = {
        "source": "test",
        "source_record_id": f"t-{uuid.uuid4()}",
        "name": "Test Pantry",
        "organization_name": "Test Org",
        "phone": "856-555-0100",
        "address": "1 Main St",
        "hours_text": "Mon 9-5",
        "taxonomy_codes": ["BD-1800.2000"],
        "taxonomy_names": ["Food Pantries"],
        "categories": ["food"],
        "service_areas": ["Camden County, NJ"],
        "missing_core": [],
        "required_documents": [],
        "languages": [],
        "last_seen_at": datetime.now(UTC),
        "first_seen_at": datetime.now(UTC) - timedelta(days=1),
    }
    fields.update(overrides)
    async with database.SessionLocal() as db:
        row = ResourceService(**fields)
        db.add(row)
        await db.commit()
        return row.id


@pytest.mark.anyio
async def test_search_filters_by_category_county_and_text():
    marker = uuid.uuid4().hex[:10]
    pantry = await _seed(name=f"Pantry {marker}")
    await _seed(name=f"Shelter {marker}", categories=["housing-bills"], taxonomy_codes=["BH-1800"])
    far = await _seed(name=f"Pantry far {marker}", service_areas=["Bergen County, NJ"])
    statewide = await _seed(name=f"Statewide {marker}", service_areas=["NJ"])
    await _seed(name=f"Closed {marker}", status="inactive")
    incomplete = await _seed(name=f"Pantry no hours {marker}", hours_text=None, missing_core=["hours"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        resp = await client.post("/resources/search", json={"query": marker, "category": "food", "county": "camden"})
        assert resp.status_code == 200
        ids = [i["id"] for i in resp.json()["items"]]
        assert pantry in ids and incomplete in ids and statewide in ids  # a statewide service serves Camden too
        assert far not in ids
        assert ids.index(pantry) < ids.index(incomplete)  # complete records first
        resp = await client.post("/resources/search", json={"query": marker})
        names = {i["name"] for i in resp.json()["items"]}
        assert f"Closed {marker}" not in names and len(names) == 5
        assert (await client.post("/resources/search", json={"category": "nope"})).status_code == 422
        assert (await client.post("/resources/search", json={"county": "Narnia"})).status_code == 422
        # A LIKE wildcard in the text is literal, not "match anything".
        assert (await client.post("/resources/search", json={"query": f"{marker}%"})).json()["total"] == 0
        assert (await client.post("/resources/search", json={"query": f"Pantry_{marker}"})).json()["total"] == 0


@pytest.mark.anyio
async def test_detail_links_back_to_nj211_and_hides_inactive_records():
    row_id = await _seed(source="nj211", source_record_id="abc-123-def")
    gone = await _seed(status="inactive")
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get(f"/resources/{row_id}")).json()
        assert body["source_url"] == "https://search.nj211.org/search/abc-123-def"
        assert "raw" not in body
        assert (await client.get(f"/resources/{gone}")).status_code == 404
        cats = {c["key"]: c["count"] for c in (await client.get("/resources/categories")).json()}
        assert list(cats)[0] == "food" and cats["food"] >= 1


@pytest.mark.anyio
async def test_the_list_crawl_records_which_counties_listed_each_service(only_test_records):
    both, bergen_only = f"t-{uuid.uuid4()}", f"t-{uuid.uuid4()}"

    class ByPlace(FakeNJ211):
        async def search(self, code, place, page=1):
            self.requests += 1
            if code != "B":
                return [], 0
            results = [_listing(both)] + ([_listing(bergen_only)] if place["county"] == "Bergen" else [])
            return results, len(results)

    async with database.SessionLocal() as db:
        await refresh_nj211(db, _cfg(places=[PLACE, BERGEN], max_details_per_run=0), client=ByPlace({}))
        await refresh_nj211(db, _cfg(places=[PLACE, BERGEN], max_details_per_run=0), client=ByPlace({}))
    rows = await _rows([both, bergen_only])
    assert sorted(rows[both].listed_in_counties) == ["Bergen", "Camden"]  # no duplicates on a second crawl
    assert rows[bergen_only].listed_in_counties == ["Bergen"]


def test_the_list_crawl_starts_somewhere_new_each_day():
    places = [{"county": c} for c in "ABC"]
    day = datetime(2026, 10, 16, tzinfo=UTC)
    starts = {_rotated(places, day + timedelta(days=i))[0]["county"] for i in range(3)}
    assert starts == {"A", "B", "C"}
    assert sorted(p["county"] for p in _rotated(places, day)) == ["A", "B", "C"]


@pytest.mark.anyio
async def test_county_search_ranks_local_then_statewide_and_flags_statewide():
    marker = uuid.uuid4().hex[:10]
    named = await _seed(name=f"A named {marker}", service_areas=["Bergen County, NJ"])
    listed = await _seed(name=f"B listed {marker}", service_areas=[], listed_in_counties=["Bergen"])
    statewide = await _seed(name=f"C statewide {marker}", service_areas=["NJ"])
    everywhere = await _seed(name=f"D listed everywhere {marker}", service_areas=[], listed_in_counties=[f"c{i}" for i in range(12)])
    camden_only = await _seed(name=f"E camden {marker}", service_areas=[], listed_in_counties=["Camden"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        items = (await client.post("/resources/search", json={"query": marker, "county": "Bergen"})).json()["items"]
    ids = [i["id"] for i in items]
    assert camden_only not in ids
    assert ids.index(named) < ids.index(statewide) and ids.index(listed) < ids.index(statewide)
    by_id = {i["id"]: i for i in items}
    assert by_id[statewide]["statewide"] and not by_id[named]["statewide"]
    # Listed for 12 counties' searches: statewide in practice, so it shows
    # for Bergen too, flagged, after the local ones.
    assert by_id[everywhere]["statewide"] and ids.index(listed) < ids.index(everywhere)


@pytest.mark.anyio
async def test_types_are_this_categorys_kinds_counted_without_the_chosen_type():
    marker = uuid.uuid4().hex[:10]
    await _seed(name=f"Pantry {marker}", taxonomy_codes=["BD-1800.2000", "BM-6500.6500-650"], taxonomy_names=["Food Pantries", "Personal/Grooming Supplies"])
    await _seed(name=f"Pantry two {marker}", taxonomy_codes=["BD-1800.2000"], taxonomy_names=["Food Pantries"])
    await _seed(name=f"Kitchen {marker}", taxonomy_codes=["BD-5000.8300"], taxonomy_names=["Soup Kitchens"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = {"category": "food", "query": marker, "type": "BD-5000.8300"}
        types = (await client.post("/resources/types", json=body)).json()
        assert [(t["name"], t["count"]) for t in types] == [("Food Pantries", 2), ("Soup Kitchens", 1)]  # hygiene isn't a food type
        listed = (await client.post("/resources/search", json=body)).json()
        assert [i["name"] for i in listed["items"]] == [f"Kitchen {marker}"]
        assert (await client.post("/resources/types", json={"query": marker})).status_code == 422


@pytest.mark.anyio
async def test_category_counts_follow_the_chosen_county():
    marker = uuid.uuid4().hex[:10]
    await _seed(name=f"Bergen pantry {marker}", categories=["everyday-needs"], service_areas=["Bergen County, NJ"])
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        everywhere = {c["key"]: c["count"] for c in (await client.get("/resources/categories")).json()}
        bergen = {c["key"]: c["count"] for c in (await client.get("/resources/categories?county=bergen")).json()}
        sussex = {c["key"]: c["count"] for c in (await client.get("/resources/categories?county=Sussex")).json()}
        assert (await client.get("/resources/categories?county=Narnia")).status_code == 422
    # The Bergen-only listing counts everywhere and in Bergen, not in Sussex.
    assert bergen["everyday-needs"] >= 1
    assert sussex["everyday-needs"] < everywhere["everyday-needs"]
