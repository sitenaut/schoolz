"""local_events/sources/yodel.py against a synthetic widget page shaped like
the real one (events.yodel.today, the calendar Macaroni KID embeds)."""
import json
from functools import partial

import httpx
import pytest

from local_events.sources import yodel
from local_events.sources.yodel import YodelSource, parse_flight

WIDGET = "https://events.yodel.today/y/widget/abc123"
ACTION_ID = "7fcbc7f78d30fcf557d505889628104e6e09eda303"
# Multi-byte on purpose: a T row's length is in UTF-8 bytes, not characters.
LONG_DESC = "Pie contest — FREE face painting \U0001F383\nBring the family!"


def _event(eid, name, start, *, description, categories, pricing=None, cancelled=None):
    return {
        "event_id": eid, "event_name": name, "description": description, "start": start,
        "end": None, "all_day": False, "occurance_id": int(start[:10].replace("-", "")),
        "location": {"full": "242 Kings Hwy E, Haddonfield, NJ 08033, USA",
                     "geolocation": {"type": "Point", "coordinates": [-75.03, 39.89]}},
        "organizer": {"organization_name": "Borough of Haddonfield"},
        "categories": [{"name": c} for c in categories], "pricing": pricing, "cancelled": cancelled,
        "website_url": None, "tickets_url": None, "register_url": None, "content": {"tags": []},
    }


def _page_html() -> str:
    desc_bytes = LONG_DESC.encode("utf-8")
    props = {
        "initialEvents": [
            _event("e1", "Harvest Week", "2026-09-26T15:00:00.000Z", description="$36",
                   categories=["Kids & Family", "Festivals/Fairs"], pricing={"is_free": True, "amount_min": None, "amount_max": None}),
            _event("gone", "Cancelled thing", "2026-09-27T15:00:00.000Z", description="x", categories=[], cancelled=True),
        ],
        "initialHasMore": True, "initialNextPageCursor": "CURSOR1", "fetchEvents": "$h3f",
    }
    flight = (
        f'3f:{json.dumps({"id": ACTION_ID, "bound": None})}\n'
        f'36:T{len(desc_bytes):x},{LONG_DESC}'
        f'30:{json.dumps(["$", "$L35", None, props])}\n'
    )
    # The page splits the payload across push() calls as JS string literals.
    half = len(flight) // 2
    pushes = "".join(f"<script>self.__next_f.push([1,{json.dumps(part)}])</script>" for part in (flight[:half], flight[half:]))
    return f"<html><body>{pushes}</body></html>"


def _page2() -> bytes:
    events = [_event("e2", "Pottery Class", "2026-10-03T14:00:00.000Z", description="Ages 5+",
                     categories=["Classes/Workshops"], pricing={"is_free": False, "amount_min": 36, "amount_max": 36})]
    return ('0:{"a":"$@1"}\n1:' + json.dumps({"events": events, "hasMore": False, "nextPageCursor": None}) + "\n").encode()


def test_parse_flight_text_rows_are_byte_counted():
    desc = LONG_DESC.encode()
    rows = parse_flight(b"36:T%x," % len(desc) + desc + b'1:{"ok":true}\n')
    assert rows == {"36": LONG_DESC, "1": {"ok": True}}


@pytest.mark.anyio
async def test_yodel_reads_first_page_then_loads_more(monkeypatch):
    posts = []

    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=_page_html())
        posts.append((request.headers["Next-Action"], json.loads(request.content)))
        return httpx.Response(200, content=_page2())

    monkeypatch.setattr(yodel.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    src = YodelSource("macaronikid_cherryhill", WIDGET, fallback_url="https://cherryhill.macaronikid.com/events",
                      default_categories=["kids", "family"])
    events = await src.fetch()

    assert [e.title for e in events] == ["Harvest Week", "Pottery Class"]  # cancelled one skipped
    assert posts == [(ACTION_ID, [2, False, {"widget_id": "abc123"}, {}, None, 0, False, "CURSOR1"])]
    harvest, pottery = events
    assert harvest.description == LONG_DESC  # resolved from the "$36" text row
    assert harvest.source_event_id == "e1:20260926"
    assert harvest.is_free is True and harvest.latitude == 39.89 and harvest.venue_name == "Borough of Haddonfield"
    assert harvest.default_categories == ["kids", "family", "outdoor"]
    assert harvest.url == "https://cherryhill.macaronikid.com/events"
    assert pottery.price_min == 36 and "class" in pottery.default_categories
    assert src.partial_failures == []


@pytest.mark.anyio
async def test_yodel_keeps_first_page_when_load_more_fails(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        if request.method == "GET":
            return httpx.Response(200, text=_page_html())
        return httpx.Response(404, text="Server action not found")

    monkeypatch.setattr(yodel.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    src = YodelSource("mk", WIDGET)
    events = await src.fetch()
    assert [e.title for e in events] == ["Harvest Week"]
    assert len(src.partial_failures) == 1 and "page 2" in src.partial_failures[0]
