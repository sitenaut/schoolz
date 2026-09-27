"""services/arbiter.py against synthetic responses shaped like the real
ArbiterLive calendarmonth API."""
from datetime import date
from functools import partial

import httpx
import pytest

from services import arbiter
from services.arbiter import entity_id_from_athletics_url, fetch_events


def test_entity_id_from_athletics_url():
    assert entity_id_from_athletics_url("https://www.arbiterlive.com/m/team/4714") == "4714"
    assert entity_id_from_athletics_url("https://easternvikings.arbiterwebsites.com/") is None
    assert entity_id_from_athletics_url(None) is None
    assert entity_id_from_athletics_url("") is None


def _month_payload(year, month, events):
    return {"year": year, "month": month, "days": [e["day"] for e in events], "events": events}


def _event(day, title, opponent, time="4:00 PM", game_id=1):
    return {"day": day, "time": time, "title": title, "opponent": opponent, "location": "Field", "isHome": True, "sportId": 1, "type": "game", "url": f"/m/game/{game_id}?entityId=4714"}


@pytest.mark.anyio
async def test_fetch_events_maps_fields_and_combines_title_opponent(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params["entityId"] == "4714"
        return httpx.Response(200, json=_month_payload(2026, 9, [_event(1, "Soccer - Girls Varsity", "vs West Deptford High School", game_id=102129453)]))

    monkeypatch.setattr(arbiter.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    events = await fetch_events("4714", date(2026, 9, 1), date(2026, 9, 30))
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Soccer - Girls Varsity vs West Deptford High School"
    assert e["external_uid"] == "102129453"
    assert e["description"] == "Field"
    assert e["is_all_day"] is False
    assert e["start_date"].isoformat() == "2026-09-01T16:00:00-04:00"


@pytest.mark.anyio
async def test_fetch_events_spans_multiple_months(monkeypatch):
    calls = []

    def handler(request: httpx.Request) -> httpx.Response:
        month = int(request.url.params["month"])
        calls.append(month)
        return httpx.Response(200, json=_month_payload(2026, month, [_event(15, "Football", "vs Rival", game_id=month)]))

    monkeypatch.setattr(arbiter.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    events = await fetch_events("4714", date(2026, 9, 20), date(2026, 11, 10))
    assert calls == [9, 10, 11]
    # Sep 15 falls before the requested window and is dropped; Nov 15 falls after it and is dropped too.
    assert [e["external_uid"] for e in events] == ["10"]


@pytest.mark.anyio
async def test_fetch_events_no_time_is_all_day(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json=_month_payload(2026, 9, [_event(5, "Tournament", "vs Various", time=None, game_id=9)]))

    monkeypatch.setattr(arbiter.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    events = await fetch_events("4714", date(2026, 9, 1), date(2026, 9, 30))
    assert events[0]["is_all_day"] is True
