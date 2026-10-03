"""local_events/sources/ccls.py against a synthetic Drupal JSON:API response
shaped like the real one (events.camdencountylibrary.org)."""
from functools import partial

import httpx
import pytest

from local_events.sources import ccls
from local_events.sources.ccls import CCLSSource, list_branches

_LOCATIONS = {
    "data": [
        {"id": "loc-voorhees", "attributes": {"title": "Voorhees"}},
        {"id": "loc-bellmawr", "attributes": {"title": "Bellmawr"}},
        {"id": "loc-virtual", "attributes": {"title": "Virtual"}},
        {"id": "loc-offsite", "attributes": {"title": "Off Site"}},
        {"id": "loc-systemwide", "attributes": {"title": "System Wide"}},
    ]
}


def _event(nid, title, start, end, alias):
    return {
        "id": f"node-{nid}",
        "attributes": {
            "drupal_internal__nid": nid,
            "title": title,
            "path": {"alias": alias},
            "field_date_time": {"value": start, "end_value": end},
            "field_text_teaser": {"value": "Join us!"},
            "event_thumbnail": "https://events.camdencountylibrary.org/thumb.png",
        },
    }


def _handler(events_page1, events_page2=None):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jsonapi/node/location":
            return httpx.Response(200, json=_LOCATIONS)
        assert request.url.path == "/jsonapi/node/event"
        if "offset" in str(request.url):
            return httpx.Response(200, json={"data": events_page2 or [], "links": {}})
        links = {}
        if events_page2 is not None:
            links["next"] = {"href": "https://events.camdencountylibrary.org/jsonapi/node/event?page[offset]=50"}
        return httpx.Response(200, json={"data": events_page1, "links": links})

    return handler


@pytest.mark.anyio
async def test_lists_real_branches_only():
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_LOCATIONS)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        branches = await list_branches(client)

    assert branches == {"Voorhees": "loc-voorhees", "Bellmawr": "loc-bellmawr"}


@pytest.mark.anyio
async def test_fetch_maps_fields_and_tags_with_library_category(monkeypatch):
    events = [_event(1, "(A) Crafternoons", "2026-09-28T13:00:00-04:00", "2026-09-28T14:00:00-04:00", "/event/2026-09-28/crafternoons")]
    monkeypatch.setattr(ccls.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(_handler(events))))

    source = CCLSSource(name="ccls_voorhees", branch_name="voorhees")  # case-insensitive match
    out = await source.fetch()

    assert len(out) == 1
    event = out[0]
    assert event.title == "(A) Crafternoons"
    assert event.url == "https://events.camdencountylibrary.org/event/2026-09-28/crafternoons"
    assert event.venue_name == "Camden County Library - voorhees"
    assert event.default_categories == ["library"]
    assert event.description == "Join us!"
    assert event.start_time.isoformat() == "2026-09-28T13:00:00-04:00"


@pytest.mark.anyio
async def test_unknown_branch_returns_nothing(monkeypatch):
    monkeypatch.setattr(ccls.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(_handler([]))))

    source = CCLSSource(name="ccls_ghost", branch_name="Not A Real Branch")
    assert await source.fetch() == []


@pytest.mark.anyio
async def test_follows_pagination_via_links_next(monkeypatch):
    page1 = [_event(1, "Page 1 Event", "2026-09-28T13:00:00-04:00", None, "/event/1")]
    page2 = [_event(2, "Page 2 Event", "2026-09-29T13:00:00-04:00", None, "/event/2")]
    monkeypatch.setattr(ccls.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(_handler(page1, page2))))

    source = CCLSSource(name="ccls_voorhees", branch_name="Voorhees", max_pages=5)
    out = await source.fetch()

    assert [e.title for e in out] == ["Page 1 Event", "Page 2 Event"]


@pytest.mark.anyio
async def test_requests_only_the_fields_the_parser_reads(monkeypatch):
    """Full Drupal nodes made a page ~630 KB / 17-43 s and timed the source out
    on prod; the sparse fieldset must name every attribute _to_event uses."""
    seen = []
    inner = _handler([_event(1, "Story Time", "2026-09-28T13:00:00-04:00", None, "/event/1")])

    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.path == "/jsonapi/node/event":
            seen.append(request.url.params.get("fields[node--event]"))
        return inner(request)

    monkeypatch.setattr(ccls.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    out = await CCLSSource(name="ccls_voorhees", branch_name="Voorhees").fetch()

    assert len(seen) == 1 and seen[0]
    requested = set(seen[0].split(","))
    assert {"title", "field_date_time", "field_text_teaser", "path", "event_thumbnail", "drupal_internal__nid"} <= requested
    assert out[0].title == "Story Time" and out[0].description == "Join us!" and out[0].url.endswith("/event/1")
