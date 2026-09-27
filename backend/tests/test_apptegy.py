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


_FIND_US_TEMPLATE = """<html><body><footer>
  <div class="footer-column-main">
    <div class="logo-wrapper"><img src="/logo.png" class="footer-logo"></div>
    <h2>Find Us</h2>
    <p>
      <span>Thomas Sharp Elementary </span>
      <span> 400 Comly Ave</span>
      <span>Collingswood , NJ 08107</span>
      <span><a href="tel:(856) 962-5707" class="tel-link">(856) 962-5707</a></span>
    </p>
  </div>
</footer></body></html>"""

_CONTACT_US_TEMPLATE = """<html><body><footer>
  <img src="/oaklyn-logo.png" class="footer-logo">
  <div class="contact-data">
    <div class="info bold">
      <span>Oaklyn Public School District</span>
      <span>136 Kendall Boulevard</span>
      <span>Oaklyn, NJ 08107</span>
      <span>Number: <span><a href="tel:856-858-0335" class="tel-link">856-858-0335</a></span></span>
    </div>
  </div>
</footer></body></html>"""


@pytest.mark.anyio
async def test_discover_school_info_find_us_template(monkeypatch):
    async def fake_fetch_html(url, wait_for_selector=None, timeout_ms=15000):
        return {"html": _FIND_US_TEMPLATE}

    monkeypatch.setattr(apptegy.scraper_client, "fetch_html", fake_fetch_html)

    info = await apptegy.discover_school_info("https://www.collsk12.org/o/tse")
    assert info["address"] == "400 Comly Ave, Collingswood , NJ 08107"
    assert info["main_phone"] == "(856) 962-5707"
    assert info["logo_url"] == "https://www.collsk12.org/logo.png"


@pytest.mark.anyio
async def test_discover_school_info_contact_us_template(monkeypatch):
    """Regression: Oaklyn's site uses a different footer template
    ("Contact Us:", a .contact-data/.info block with the phone nested one
    level deeper) from Collingswood/Woodlynne's "Find Us" template - the
    first version of this parser only handled the first template and
    silently returned nothing for Oaklyn."""

    async def fake_fetch_html(url, wait_for_selector=None, timeout_ms=15000):
        return {"html": _CONTACT_US_TEMPLATE}

    monkeypatch.setattr(apptegy.scraper_client, "fetch_html", fake_fetch_html)

    info = await apptegy.discover_school_info("https://www.oaklynschool.org")
    assert info["address"] == "136 Kendall Boulevard, Oaklyn, NJ 08107"
    assert info["main_phone"] == "856-858-0335"
    assert info["logo_url"] == "https://www.oaklynschool.org/oaklyn-logo.png"


@pytest.mark.anyio
async def test_discover_school_info_returns_nulls_when_footer_never_loads(monkeypatch):
    async def fake_fetch_html(url, wait_for_selector=None, timeout_ms=15000):
        raise TimeoutError("no footer on this page")

    monkeypatch.setattr(apptegy.scraper_client, "fetch_html", fake_fetch_html)

    assert await apptegy.discover_school_info("https://example.org") == {"address": None, "main_phone": None, "logo_url": None}


@pytest.mark.anyio
async def test_fetch_staff_empty_directory_returns_nothing(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"directories": [], "meta": {"links": {"total_entries": 0}}})

    monkeypatch.setattr(apptegy.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    assert await apptegy.fetch_staff("8796") == []
