"""services/apptegy.py against synthetic responses shaped like the real
Apptegy (Thrillshare) API (thrillshare-cmsv2.services.thrillshare.com)."""
from datetime import date
from functools import partial

import httpx
import pytest

from services import apptegy


@pytest.mark.anyio
async def test_fetch_events_maps_fields(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/api/v4/o/8801/cms/events"
        return httpx.Response(
            200,
            json={
                "events": [
                    {
                        "id": 61418802,
                        "title": "Preschool Meet and Greet! ",
                        "description": "This is for enrolled students.",
                        "start_at": "2026-09-01T09:30:00.000-04:00",
                        "end_at": "2026-09-01T10:30:00.000-04:00",
                        "all_day": False,
                    },
                    {"id": 2, "title": "No start", "start_at": None},
                ]
            },
        )

    monkeypatch.setattr(apptegy.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    events = await apptegy.fetch_events("8801", date(2026, 9, 1), date(2026, 10, 31))
    assert len(events) == 1
    e = events[0]
    assert e["title"] == "Preschool Meet and Greet!"
    assert e["external_uid"] == "61418802"
    assert e["start_date"].isoformat() == "2026-09-01T09:30:00-04:00"
    assert e["is_all_day"] is False


@pytest.mark.anyio
async def test_fetch_staff_paginates_and_drops_nameless_entries(monkeypatch):
    page1 = {
        "directories": [
            {"id": 1, "full_name": "Suzanne Slominski", "title": "Teacher", "email": "s@example.org", "phone_number": "", "department": ""},
            {"id": 2, "full_name": "", "title": "Ghost"},
        ],
        "meta": {"links": {"next": "https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/12858/cms/directories?locale=en&page_no=2"}},
    }
    page2 = {
        "directories": [{"id": 3, "full_name": "Maria Rivera", "title": "Sodexo Supervisor", "email": "m@example.org", "phone_number": "856-962-8822", "department": "Food Service"}],
        "meta": {"links": {"next": None}},
    }

    def handler(request: httpx.Request) -> httpx.Response:
        if "page_no=2" in str(request.url):
            return httpx.Response(200, json=page2)
        return httpx.Response(200, json=page1)

    monkeypatch.setattr(apptegy.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    roster = await apptegy.fetch_staff("12858")

    assert [p["full_name"] for p in roster] == ["Suzanne Slominski", "Maria Rivera"]
    assert roster[1]["department"] == "Food Service"
    assert roster[1]["phone"] == "856-962-8822"


@pytest.mark.anyio
async def test_fetch_staff_empty_directory_returns_nothing(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"directories": [], "meta": {"links": {"total_entries": 0}}})

    monkeypatch.setattr(apptegy.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    assert await apptegy.fetch_staff("8796") == []
