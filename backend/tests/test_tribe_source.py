"""local_events/sources/tribe.py (The Events Calendar's WordPress REST API)
against payloads shaped like visitsouthjersey.com / downtownhaddonfield.com."""
from functools import partial

import httpx
import pytest

from local_events.sources import tribe
from local_events.sources.tribe import TribeEventsSource

BASE = "https://example-tribe.test"


def _venue(name, lat=None, lng=None, city=None, zip_=None, address=None):
    return {"venue": name, "geo_lat": lat, "geo_lng": lng, "city": city, "zip": zip_, "address": address, "stateprovince": "NJ"}


def _event(eid, title, start, *, venue, cost="", categories=(), all_day=False):
    return {
        "id": eid, "status": "publish", "title": title, "description": "<p>Fun &amp; games</p>",
        "start_date": start, "end_date": start, "all_day": all_day,
        # Haddonfield's real shape: labelled UTC, but start_date is local wall time.
        "timezone": "UTC+0", "utc_start_date": start,
        "url": f"{BASE}/event/{eid}/", "cost": cost, "image": False,
        "venue": venue, "categories": [{"name": c} for c in categories],
    }


PAGE1 = {
    "events": [
        _event(1, "Sunflower &amp; Fall Festival", "2026-09-26 11:00:00",
               venue=_venue("The Red Barn", 39.94, -75.02, "Cherry Hill", "08002"), cost="Free",
               categories=["Adventure &amp; Family Fun"]),
        _event(2, "Cape May Village Day", "2026-09-26 10:00:00",
               venue=_venue("Cold Spring Village", 38.97, -74.93, "Cape May", "08204"), cost="$20"),
    ],
    "next_rest_url": f"{BASE}/wp-json/tribe/events/v1/events?page=2&per_page=50",
}
PAGE2 = {
    "events": [
        # No coordinates: zip decides.
        _event(3, "Line Dancing", "2026-09-27 19:00:00",
               venue=_venue("The Grove", address="1022 Almond Road Pittsgrove, New Jersey 08318"), cost="$5.00 – $27.50"),
        _event(4, "Collingswood Crafts", "2026-09-27 12:00:00",
               venue=_venue("Downtown Collingswood", zip_="08108"), categories=["Unmapped Site Category"]),
        # No location at all ([] is what the API sends): kept.
        _event(5, "Hedge Field Fall Fest", "2026-09-27 11:00:00", venue=[], all_day=True),
    ],
    "next_rest_url": None,
}


@pytest.mark.anyio
async def test_tribe_pages_filters_by_distance_and_reads_local_time(monkeypatch):
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request.url)
        return httpx.Response(200, json=PAGE2 if request.url.params.get("page") == "2" else PAGE1)

    monkeypatch.setattr(tribe.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    src = TribeEventsSource("vsj", BASE, days_ahead=30, max_miles=25)
    events = {e.source_event_id: e for e in await src.fetch()}

    assert len(requests) == 2
    assert requests[0].params["start_date"] and requests[0].params["end_date"].endswith("23:59:59")
    assert set(events) == {"1", "4", "5"}  # Cape May (coords) and Pittsgrove 083xx (zip) dropped
    assert src.skipped_far == 2

    festival = events["1"]
    assert festival.title == "Sunflower & Fall Festival"
    assert festival.description == "Fun & games"
    assert festival.start_time.isoformat() == "2026-09-26T11:00:00-04:00"  # local, despite "UTC+0"
    assert festival.is_free is True and festival.price_min == 0
    assert festival.default_categories == ["family", "outdoor"]
    assert festival.venue_address == "Cherry Hill, NJ, 08002"
    assert events["4"].default_categories == []  # unmapped site categories are dropped
    assert events["5"].venue_name is None and events["5"].all_day is True


def test_price_parsing():
    assert tribe._price({"cost": "$5.00 – $27.50"}) == (5.0, 27.5, False)
    assert tribe._price({"cost": "Free"}) == (0.0, 0.0, True)
    assert tribe._price({"cost": ""}) == (None, None, None)
    assert tribe._price({"cost": "Donation"}) == (None, None, None)
