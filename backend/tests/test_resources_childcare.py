import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import copy
import json
from pathlib import Path

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
import scraper_client
from main import app
from models import ResourceService
from resources import childcarenj
from resources.refresh import refresh_childcarenj
from scheduler.errors import parse_warning
from scheduler.jobs import resources_childcare

FIXTURE = json.loads((Path(__file__).parent / "fixtures" / "childcarenj_providers.json").read_text(encoding="utf-8"))
CENTER, HOME, CAMP = FIXTURE["Facilities"]


# ---- normalization ----------------------------------------------------------


def test_a_center_reads_as_a_listing():
    unknown: set[str] = set()
    f = childcarenj.fields(CENTER, "Camden", unknown)
    assert f["name"] == "Little Acorns Learning Center"
    assert f["address"] == "100 Example Avenue"
    assert f["hours_text"] == "Mon-Fri 7:00 AM-5:30 PM"
    assert f["eligibility_text"] == "Cares for infants, toddlers, preschoolers and school-age children."
    assert f["fees"].startswith("Infants: $425/week. Toddlers: $425/week.")
    assert "Accepts state child care assistance (CCAP)" in f["description"]
    assert f["service_areas"] == ["Camden County, NJ"] and f["listed_in_counties"] == ["Camden"]
    assert (f["taxonomy_codes"], f["taxonomy_names"]) == (["PH-1250.1400"], ["Child Care Centers"])
    assert f["website"] == "https://www.example.org"
    assert unknown == set()


def test_a_home_daycare_is_never_placed_closer_than_its_town_and_no_email_is_kept():
    record = dict(HOME, ProgramAddressStreetNumber="12", ProgramAddressStreetName="Private Lane")
    f = childcarenj.fields(record, "Camden", set())
    assert f["address"] is None and f["city"] == "Sicklerville"
    assert f["email"] is None and childcarenj.fields(CENTER, "Camden", set())["email"] is None
    raw = childcarenj.storable_raw(record)
    assert "ProgramEmail" not in raw and "ProgramAddressStreetName" not in raw and "ProgramAddressStreetNumber" not in raw
    assert "ProgramEmail" not in childcarenj.storable_raw(CENTER)
    assert f["taxonomy_names"] == ["Family Child Care"]


def test_names_in_capitals_are_title_cased_and_others_left_alone():
    assert childcarenj.display_name("A BYRD'S NEST DAYCARE LLC") == "A Byrd's Nest Daycare LLC"
    assert childcarenj.display_name("ABC Learning Station - Pennsville") == "ABC Learning Station - Pennsville"


def test_camps_are_their_own_kind():
    assert childcarenj.kind(CAMP) == "camp"
    assert childcarenj.fields(CAMP, "Camden", set())["taxonomy_codes"] == ["PL-6400.1500-820"]
    assert childcarenj.fields(CAMP, "Camden", set())["description"].startswith("Licensed youth camp.")


def test_hours_fold_runs_of_identical_days():
    record = {f"DailyOpeningTime{d}": "" for d, _ in childcarenj.DAYS} | {f"DailyClosingTime{d}": "" for d, _ in childcarenj.DAYS}
    for day in ("Monday", "Tuesday", "Wednesday"):
        record[f"DailyOpeningTime{day}"], record[f"DailyClosingTime{day}"] = "06:30:00", "18:00:00"
    record["DailyOpeningTimeSaturday"], record["DailyClosingTimeSaturday"] = "08:00:00", "12:00:00"
    assert childcarenj.hours_text(record) == "Mon-Wed 6:30 AM-6:00 PM; Sat 8:00 AM-12:00 PM"
    assert childcarenj.hours_text({}) is None


def test_a_code_missing_from_the_lookup_is_reported_not_dropped_silently():
    unknown: set[str] = set()
    childcarenj.fields(dict(CENTER, SpecialSchedules=[99]), "Camden", unknown)
    assert unknown == {"SpecialSchedules=99"}


def test_the_endpoint_gets_every_parameter_the_search_page_sends():
    params = childcarenj.search_params("Cape May", 0)
    assert params["county"] == "Cape May" and params["pageSize"] == 500
    assert {"sortKey", "sortDirection", "mccynplus", "programTypes", "zipcode"} <= set(params)


def test_json_wrapped_in_chromes_viewer_is_unwrapped():
    wrapped = '<html><head></head><body><pre style="word-wrap: break-word;">{"Facilities": [{"UniqueProgramID": "1", "ProgramName": "A &amp; B"}], "ResultCount": 1}</pre></body></html>'
    records, total = childcarenj.parse_response(wrapped)
    assert total == 1 and records[0]["ProgramName"] == "A & B"


def test_a_non_json_answer_is_an_error_not_an_empty_county():
    with pytest.raises(ValueError):
        childcarenj.parse_response(b'{"Something": []}')


# ---- the refresh ------------------------------------------------------------


class FakeChildCareNJ:
    def __init__(self, by_county, block=False):
        self.by_county = by_county
        self.block = block
        self.requests = 0

    async def providers(self, county, page=0):
        self.requests += 1
        if self.block:
            raise childcarenj.Blocked("HTTP 403 for Camden")
        records = self.by_county.get(county, [])
        return copy.deepcopy(records), len(records) + (1 if county == "Camden" else 0)


@pytest.fixture
async def only_test_records():
    async with database.SessionLocal() as db:
        await db.execute(update(ResourceService).where(ResourceService.source == childcarenj.SOURCE).values(source="set-aside"))
        await db.commit()


async def _rows():
    async with database.SessionLocal() as db:
        rows = (await db.execute(select(ResourceService).where(ResourceService.source == childcarenj.SOURCE))).scalars().all()
        return {r.source_record_id: r for r in rows}


CFG = {"counties": ["Camden", "Salem"]}


async def _run(cfg, client):
    async with database.SessionLocal() as db:
        return await refresh_childcarenj(db, cfg, client=client)


@pytest.mark.anyio
async def test_first_run_stores_every_county_and_counts_the_shortfall(only_test_records):
    hidden = dict(CAMP, UniqueProgramID="900009", Hidden=True)
    summary = await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER, HOME, hidden], "Salem": [CAMP]}))
    assert (summary["new"], summary["listed"], summary["hidden"], summary["counties"]) == (3, 3, 1, 2)
    assert summary["short_counts"] == ["Camden: 3 of 4"]
    rows = await _rows()
    assert set(rows) == {"900001", "900002", "900003"}
    assert rows["900003"].listed_in_counties == ["Salem"]
    assert rows["900001"].categories == ["kids-family"] and rows["900001"].missing_core == []
    assert rows["900002"].address is None and "ProgramEmail" not in rows["900002"].raw
    assert rows["900001"].detail_fetched_at is not None


@pytest.mark.anyio
async def test_an_unchanged_provider_is_not_rewritten_and_a_changed_one_is(only_test_records):
    await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER, HOME]}))
    moved = dict(HOME, DailyClosingTimeMonday="18:00:00")
    summary = await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER, moved]}))
    assert (summary["new"], summary["changed"]) == (0, 1)
    assert "6:00 PM" in (await _rows())["900002"].hours_text


@pytest.mark.anyio
async def test_providers_go_inactive_after_two_complete_passes_without_them(only_test_records):
    await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER, HOME]}))
    for _ in range(2):
        await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER]}))
    rows = await _rows()
    assert rows["900002"].status == "inactive" and rows["900001"].status == "active"
    summary = await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER, HOME]}))
    assert summary["reactivated"] == 1


@pytest.mark.anyio
async def test_a_failed_county_or_a_refusal_marks_nothing_missing(only_test_records):
    await _run(CFG, client=FakeChildCareNJ({"Camden": [CENTER, HOME]}))

    class SalemFails(FakeChildCareNJ):
        async def providers(self, county, page=0):
            if county == "Salem":
                raise ValueError("HTTP 302 text/html for Salem - endpoint changed?")
            return await super().providers(county, page)

    for _ in range(2):
        summary = await _run(CFG, client=SalemFails({"Camden": [CENTER]}))
        assert summary["errors"] and summary["deactivated"] == 0
        blocked = await _run(CFG, client=FakeChildCareNJ({}, block=True))
        assert blocked["blocked"]
    assert (await _rows())["900002"].status == "active"


def _returning(summary):
    async def fake(db, cfg):
        return summary

    return fake


@pytest.mark.anyio
async def test_job_reports_problems_as_coded_warnings(monkeypatch):
    base = {"listed": 5, "errors": [], "blocked": None, "unknown_codes": []}
    for outcome, code in [
        ({"blocked": "HTTP 403 for Camden"}, "resource_source_blocked"),
        ({"errors": ["Salem: timeout"]}, "resource_source_partial"),
        ({"listed": 0}, "resource_source_empty"),
        ({"unknown_codes": ["SpecialSchedules=99"]}, "resource_unknown_codes"),
        ({}, None),
    ]:
        monkeypatch.setattr(resources_childcare, "refresh_childcarenj", _returning(dict(base, **outcome)))
        assert parse_warning(await resources_childcare.run(None, resources_childcare.DEFAULT_PARAMS)) == code


@pytest.mark.anyio
async def test_detail_links_back_to_the_providers_childcarenj_page(only_test_records):
    await _run({"counties": ["Camden"]}, client=FakeChildCareNJ({"Camden": [CENTER, HOME]}))
    rows = await _rows()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        body = (await client.get(f"/resources/{rows['900001'].id}")).json()
        assert body["source_url"] == "https://www.childcarenj.gov/providerdetails.aspx?uniqueProgramID=900001&licenseNumber=08000001"
        home = (await client.get(f"/resources/{rows['900002'].id}")).json()
        assert home["address"] is None and home["email"] is None


# ---- routes: direct, then the scrapers --------------------------------------


def _client_with(handler):
    client = childcarenj.ChildCareNJClient()
    client._http = httpx.AsyncClient(transport=httpx.MockTransport(handler))
    return client


@pytest.mark.anyio
async def test_a_direct_refusal_moves_the_run_to_the_scrapers(monkeypatch):
    asked = []

    async def fake_any(url, timeout_ms=45_000, expect_content_type=None, prefer=None):
        asked.append((url, prefer))
        return {"status": 200, "content_type": "application/json", "text": json.dumps(FIXTURE), "service": "scraper.example"}

    monkeypatch.setattr(scraper_client, "fetch_raw_text_from_any", fake_any)
    direct = []
    client = _client_with(lambda request: direct.append(request) or httpx.Response(403, text="Cloudflare"))
    records, total = await client.providers("Cape May")
    assert len(records) == 3 and total == 4
    assert len(direct) == 1 and client.via_scraper and client.route == "scraper:scraper.example"
    assert "county=Cape+May" in asked[0][0] and "sortKey=ProgramName" in asked[0][0] and asked[0][1] is None
    client._last = 0
    await client.providers("Salem")
    assert len(direct) == 1 and asked[1][1] == "scraper.example"  # no new direct try; the working scraper first


@pytest.mark.anyio
async def test_every_route_refused_is_a_block(monkeypatch):
    async def refused(url, timeout_ms=45_000, expect_content_type=None, prefer=None):
        raise scraper_client.ScraperRefused("every scraper was refused")

    monkeypatch.setattr(scraper_client, "fetch_raw_text_from_any", refused)
    client = _client_with(lambda request: httpx.Response(403))
    with pytest.raises(childcarenj.Blocked):
        await client.providers("Camden")


@pytest.mark.anyio
async def test_the_scraper_walk_skips_refusals_and_wrong_content(monkeypatch):
    services = [("https://own.example", "k1"), ("https://droplet.example", "k2"), ("https://down.example", "k3"), ("https://pi.example", "k4")]
    calls = []

    async def fake_post(service_url, api_key, path, payload, timeout_s):
        calls.append(service_url)
        if service_url == "https://own.example":
            return {"status": 403, "content_type": "text/html", "body_base64": ""}
        if service_url == "https://droplet.example":
            # playwright-scraper sends no status: a Cloudflare page is only
            # visible as the wrong content type.
            return {"content_type": "text/html; charset=UTF-8", "body": "<html>Attention Required</html>"}
        if service_url == "https://down.example":
            raise httpx.ConnectError("down")
        return {"content_type": "application/json; charset=utf-8", "body": '{"Facilities": [], "ResultCount": 0}'}

    monkeypatch.setattr(scraper_client, "_services", lambda: services)
    monkeypatch.setattr(scraper_client, "_post_to", fake_post)
    url = "https://www.childcarenj.gov/Services/GetProviders.aspx?county=Salem"
    result = await scraper_client.fetch_raw_text_from_any(url, expect_content_type="json")
    assert calls == [s for s, _ in services] and result["service"] == "pi.example" and result["status"] == 200
    calls.clear()
    await scraper_client.fetch_raw_text_from_any(url, expect_content_type="json", prefer="pi.example")
    assert calls == ["https://pi.example"]

    async def all_refuse(service_url, api_key, path, payload, timeout_s):
        return {"content_type": "text/html", "body": "blocked"}

    monkeypatch.setattr(scraper_client, "_post_to", all_refuse)
    with pytest.raises(scraper_client.ScraperRefused):
        await scraper_client.fetch_raw_text_from_any(url, expect_content_type="json")
