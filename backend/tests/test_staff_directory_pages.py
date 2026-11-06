import uuid

import pytest
from sqlalchemy import select

import database
from models import School, StaffMember
from scheduler.jobs import staff_roster_scan
from services import staff_roster

pytestmark = pytest.mark.anyio


def _page(first: int, last: int, listed: int, ids: range, extra: str = "") -> str:
    label = f'<span class="fsPaginationLabel">showing {first} - {last} of {listed} constituents</span>'
    cards = "".join(
        f'<div class="fsConstituentItem" data-constituent-id="{i}"><h3 class="fsFullName">Person {i}</h3></div>' for i in ids
    )
    return label + cards + extra


def _fake_reads(monkeypatch, *reads: list[str]) -> list[dict]:
    calls, queued = [], list(reads)

    async def fake_fetch_paginated(url, next_page_selector, **kw):
        calls.append({"url": url, **kw})
        return queued.pop(0)

    monkeypatch.setattr(staff_roster.scraper_client, "fetch_paginated", fake_fetch_paginated)
    return calls


async def test_a_read_that_missed_pages_is_read_again_slower(monkeypatch):
    # Highland Regional, 2026-11-05: the droplet read 2 of the directory's 6 pages.
    calls = _fake_reads(
        monkeypatch,
        [_page(1, 2, 5, range(1, 3))],
        [_page(1, 2, 5, range(1, 3)), _page(3, 4, 5, range(3, 5)), _page(5, 5, 5, range(5, 6))],
    )
    people = await staff_roster._read_constituent_directory("https://hs.example.org/staff-directory", ["Highland"])
    assert sorted(p["constituent_id"] for p in people) == ["1", "2", "3", "4", "5"]
    assert not any(p.get("directory_short") for p in people)
    assert [(c["max_pages"], c["wait_after_click_ms"]) for c in calls] == [(25, 1200), (25, staff_roster._SLOW_CLICK_MS)]
    # Never with playwright-stealth, on any scraper: it cut these directories short.
    assert all(c["stealth"] is False for c in calls)


async def test_a_read_still_short_the_second_time_is_marked_short(monkeypatch):
    short = [_page(1, 2, 5, range(1, 3))]
    _fake_reads(monkeypatch, short, short)
    people = await staff_roster._read_constituent_directory("https://hs.example.org/staff-directory", ["Highland"])
    assert [p["directory_short"] for p in people] == [(2, 5), (2, 5)]


async def test_a_directory_longer_than_the_page_limit_is_marked_short_and_not_read_again(monkeypatch):
    # The scraper clicks through at most 25 pages; reading again can't get more.
    limit = staff_roster._MAX_PAGES
    pages = [_page(1, 10, 300, range(n * 10 + 1, n * 10 + 11)) for n in range(limit)]
    calls = _fake_reads(monkeypatch, pages)
    people = await staff_roster._read_constituent_directory("https://hs.example.org/staff-directory", ["Eastern"])
    assert len(calls) == 1 and calls[0]["max_pages"] == limit
    assert {p["directory_short"] for p in people} == {(250, 300)}


async def test_a_full_read_or_a_page_with_no_label_is_read_once(monkeypatch):
    calls = _fake_reads(monkeypatch, [_page(1, 3, 3, range(1, 4))], ["<p>No directory here</p>"])
    assert len(await staff_roster._read_constituent_directory("https://es.example.org/staff-directory", ["Elm"])) == 3
    assert await staff_roster._read_constituent_directory("https://es.example.org/contact-us", ["Elm"]) == []
    assert len(calls) == 2


async def test_placeholder_cards_still_count_toward_a_full_read(monkeypatch):
    # The label counts a "FILLER STAFF" card the parser drops.
    filler = '<div class="fsConstituentItem" data-constituent-id="99"><h3 class="fsFullName">FILLER STAFF RO-ART</h3></div>'
    calls = _fake_reads(monkeypatch, [_page(1, 3, 3, range(1, 3), filler)])
    people = await staff_roster._read_constituent_directory("https://es.example.org/staff-directory", ["Elm"])
    assert len(people) == 2 and len(calls) == 1
    assert not any(p.get("directory_short") for p in people)


async def test_a_short_roster_warns_and_keeps_everyone_on_file(monkeypatch):
    def person(cid: str, short: tuple[int, int] | None = None) -> dict:
        entry = {"constituent_id": cid, "full_name": f"Person {cid}", "title": "Teacher", "department": None, "email": f"p{cid}@example.org", "phone": None}
        if short:
            entry["directory_short"] = short
        return entry

    rosters = [[person("1"), person("2"), person("3")], [person("1", (1, 3))]]

    async def fake_fetch_roster(url, school_names=None):
        return rosters.pop(0)

    async def no_pages(*args, **kwargs):
        return []

    async def no_contact_page(*args, **kwargs):
        return [], None

    monkeypatch.setattr(staff_roster_scan, "fetch_roster", fake_fetch_roster)
    monkeypatch.setattr(staff_roster_scan, "fetch_role_staff_scraped", no_pages)
    monkeypatch.setattr(staff_roster_scan, "fetch_contacts", no_contact_page)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Elm School {tag}", slug=f"elm-{tag}", school_type="elementary", website_url=f"https://elm-{tag}.example.org")
        db.add(school)
        await db.flush()
        assert (await staff_roster_scan.run(db, {"school_id": school.id})).startswith("roster: 3 new")
        await db.flush()
        result = await staff_roster_scan.run(db, {"school_id": school.id})
        await db.flush()
        assert result.startswith("WARNING[roster_incomplete]: read 1 of the 3 people")
        ids = set((await db.execute(select(StaffMember.source_constituent_id).where(StaffMember.school_id == school.id))).scalars().all())
        assert ids == {"1", "2", "3"}


async def test_a_district_list_narrowed_to_nobody_is_not_read_again(monkeypatch):
    # A Location filter that finds no one falls back to the district-wide
    # list as before; reading all of a district slowly would only be short again.
    options = '<select name="const_search_location"><option value="54">Elm School</option></select>'
    calls = _fake_reads(monkeypatch, [_page(1, 2, 900, range(1, 3), options)], ["<p>No one here</p>"])

    async def no_redirect(*args, **kwargs):
        raise staff_roster.httpx.ConnectError("offline")

    monkeypatch.setattr(staff_roster.httpx.AsyncClient, "get", no_redirect)
    people = await staff_roster._read_constituent_directory("https://www.example.org/staff-directory", ["Elm", "Elm School"])
    assert len(calls) == 2 and len(people) == 2
    assert not any(p.get("directory_short") for p in people)


def _serve_page(monkeypatch, html: str) -> None:
    async def fake_get(self, url, **kwargs):
        return staff_roster.httpx.Response(200, text=html, request=staff_roster.httpx.Request("GET", url))

    monkeypatch.setattr(staff_roster.httpx.AsyncClient, "get", fake_get)


def _no_raw_fetch(monkeypatch) -> list[str]:
    raw = []

    async def fake_raw(url, **kwargs):
        raw.append(url)
        return b"%PDF-1.4"

    monkeypatch.setattr(staff_roster.scraper_client, "fetch_raw_bytes", fake_raw)
    return raw


async def test_a_directory_page_whose_read_fails_fails_the_scan_rather_than_being_read_as_a_pdf(monkeypatch):
    # Hamilton Township, 2026-11-06: a page pop sat over the next-page link,
    # every scraper's read failed, and that failure fell through to the PDF
    # reader, which crashed on the page (PdfminerException, error "unknown").
    from scheduler.errors import classify_exception

    _serve_page(monkeypatch, _page(1, 2, 900, range(1, 3)))
    raw = _no_raw_fetch(monkeypatch)

    async def failing_read(url, next_page_selector, **kwargs):
        request = staff_roster.httpx.Request("POST", "http://scraper.example/fetch-paginated")
        raise staff_roster.httpx.HTTPStatusError("502", request=request, response=staff_roster.httpx.Response(502, request=request))

    monkeypatch.setattr(staff_roster.scraper_client, "fetch_paginated", failing_read)
    with pytest.raises(staff_roster.httpx.HTTPStatusError) as failed:
        await staff_roster.fetch_directory_document("https://www.example.org/our-district/district-directory", ["Elm"])
    assert raw == []
    assert classify_exception(failed.value) == ("site_did_not_load", "fetch")


async def test_a_district_directory_is_narrowed_from_its_own_page_without_reading_the_district(monkeypatch):
    # The Location filter comes with the page, so the whole district (25 of
    # Hamilton Township's pages) isn't clicked through only to find it.
    options = '<select name="const_search_location"><option value="54">Elm School</option></select>'
    _serve_page(monkeypatch, _page(1, 2, 900, range(1, 3), options))
    calls = _fake_reads(monkeypatch, [_page(1, 3, 3, range(101, 104))])
    people = await staff_roster.fetch_directory_document("https://www.example.org/our-district/district-directory", ["Elm", "Elm School"])
    assert [c["url"] for c in calls] == ["https://www.example.org/our-district/district-directory?const_search_location=54"]
    assert sorted(p["constituent_id"] for p in people) == ["101", "102", "103"]
    assert all(p["location_filter"] == "Elm School" for p in people)


async def test_a_page_the_plain_get_missed_is_read_from_the_raw_fetch_and_never_as_a_pdf(monkeypatch):
    async def blocked(self, url, **kwargs):
        raise staff_roster.httpx.ConnectError("403 to a datacenter")

    monkeypatch.setattr(staff_roster.httpx.AsyncClient, "get", blocked)
    pages = iter([b"<html><p>This page has moved.</p></html>", _page(1, 2, 2, range(1, 3)).encode()])

    async def fake_raw(url, **kwargs):
        return next(pages)

    monkeypatch.setattr(staff_roster.scraper_client, "fetch_raw_bytes", fake_raw)
    calls = _fake_reads(monkeypatch, [_page(1, 2, 2, range(1, 3))])
    url = "https://www.example.org/staff-directory"
    assert await staff_roster.fetch_directory_document(url, ["Elm"]) == []
    assert len(await staff_roster.fetch_directory_document(url, ["Elm"])) == 2
    assert [c["url"] for c in calls] == [url]
