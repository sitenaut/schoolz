"""local_events/sources/ludus.py against HTML shaped like a real Ludus events
page (confirmed on collstheater.ludus.com - see the module docstring for why
sold-out status is deliberately not read)."""
from functools import partial

import httpx
import pytest

from local_events.sources import ludus
from local_events.sources.ludus import LudusSource

BASE = "https://example-theater.ludus.com/index.php?sections=events"


def _showtime(showtime_id, date_text, *, past=False, coming_soon=False):
    actions = (
        '<div class="patron_coming_soon_badge"><strong>COMING SOON</strong></div>'
        if coming_soon
        else '<div class="showtimes_item_get_tickets_button">Get Tickets</div>'
    )
    # sold_out_span/join_waitlist are rendered unconditionally by the real
    # platform regardless of true availability - included here to prove the
    # parser ignores them either way.
    return f"""
    <div class="showtimes_item" id="showtimes_item{showtime_id}" data-showtime-id="{showtime_id}"
         data-past-date="{1 if past else 0}">
      <div class="admin_showtimes_item_title"><div class="desktop_copy">
        <span class="span_link">{date_text}<span style="color:#777">&nbsp;7:00 PM</span></span>
      </div></div>
      <div class="admin_showtimes_item_actions" style="display:none;">{actions}</div>
      <div class="red_span sold_out_span">Sold Out</div>
      <div class="join_waitlist_button_container" style="display:none;"></div>
    </div>
    """


def _show(show_id, title, labels, showtimes_html):
    pills = "".join(f'<span class="event-category-pill show_item_category_pill">{l}</span>' for l in labels)
    return f"""
    <div class="show_item" data-show-id="{show_id}" data-event-categories="x;">
      <div class="show_item_category_pills" style="display:none;">{pills}</div>
      <h2 class="show_item_title"><span class="patron_heading_label">{title}</span></h2>
      <div class="show_about_buttons">
        <a href="show_location.php?show_id={show_id}"><div>Get Directions</div></a>
      </div>
      {showtimes_html}
    </div>
    """


PAGE = f"""<html><body><div id="events">
{_show("111", "3rd Annual Evening of Comedy", ["CHS"],
       _showtime("1001", "Thursday, October 29, 2026") + _showtime("1002", "Friday, October 30, 2026"))}
{_show("222", "Disney's Beauty and the Beast JR.", ["CMS"],
       _showtime("2001", "Thursday, December 10, 2026", coming_soon=True))}
{_show("333", "Community Cabaret", [],
       _showtime("3001", "Saturday, November 1, 2026") + _showtime("3002", "Tuesday, September 1, 2026", past=True))}
</div></body></html>"""


def _mock_source(page_html: str = PAGE) -> LudusSource:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page_html)

    return handler


@pytest.mark.anyio
async def test_parses_showtimes_dates_and_school_labels(monkeypatch):
    monkeypatch.setattr(ludus.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(_mock_source())))
    src = LudusSource(
        "collingswood_theater_ludus", BASE, venue_name="Collingswood Theater",
        school_labels={"CHS": "collingswood-high", "CMS": "collingswood-middle"},
    )
    events = await src.fetch()
    by_id = {e.source_event_id: e for e in events}

    # One event per performance, not per production - 4 showtimes across 3
    # shows minus the one past-dated showtime that's filtered out.
    assert set(by_id) == {"ludus:111:1001", "ludus:111:1002", "ludus:222:2001", "ludus:333:3001"}

    comedy = by_id["ludus:111:1001"]
    assert comedy.title == "3rd Annual Evening of Comedy"
    assert comedy.start_time.isoformat() == "2026-10-29T19:00:00-04:00"
    assert comedy.school_slug == "collingswood-high"
    assert comedy.venue_name == "Collingswood Theater"
    assert comedy.url == "https://example-theater.ludus.com/show_location.php?show_id=111"
    assert comedy.description is None  # on sale - nothing asserted either way

    beauty = by_id["ludus:222:2001"]
    assert beauty.school_slug == "collingswood-middle"
    assert beauty.description == "Not yet on sale."

    # Sold-out status is never asserted (see module docstring): the fixture's
    # sold_out_span is present on every showtime, but no event claims sold-out.
    assert all(e.description in (None, "Not yet on sale.") for e in events)

    cabaret = by_id["ludus:333:3001"]
    assert cabaret.school_slug is None  # no matching category label


@pytest.mark.anyio
async def test_no_show_items_raises(monkeypatch):
    monkeypatch.setattr(ludus.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(_mock_source("<html><body>nothing here</body></html>"))))
    src = LudusSource("empty", BASE)
    with pytest.raises(RuntimeError, match="no showtimes found"):
        await src.fetch()


@pytest.mark.anyio
async def test_http_error_falls_back_to_scraper(monkeypatch):
    """Confirmed real: collstheater.ludus.com 403s a direct request from a
    datacenter IP (this backend's own, and Fly's in prod) but 200s from a
    dev machine - the scraper (stealth + a residential IP) must be tried."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(403)

    monkeypatch.setattr(ludus.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    calls = []

    async def fake_render(url, **kwargs):
        calls.append((url, kwargs))
        return PAGE, url

    monkeypatch.setattr(ludus, "fetch_rendered_html", fake_render)
    src = LudusSource("collingswood_theater_ludus", BASE, school_labels={"CHS": "collingswood-high"})
    events = await src.fetch()

    assert calls == [(BASE, {"wait_for_selector": "div.show_item"})]
    assert any(e.school_slug == "collingswood-high" for e in events)


@pytest.mark.anyio
async def test_direct_and_scraper_both_failing_reports_both(monkeypatch):
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500)

    monkeypatch.setattr(ludus.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))

    async def fake_render(url, **kwargs):
        raise RuntimeError("scraper also down")

    monkeypatch.setattr(ludus, "fetch_rendered_html", fake_render)
    src = LudusSource("down", BASE)
    with pytest.raises(RuntimeError) as excinfo:
        await src.fetch()
    # httpx's own HTTPStatusError message embeds a newline, so check each
    # half separately rather than a single regex spanning both.
    assert "direct fetch:" in str(excinfo.value) and "scraper also down" in str(excinfo.value)
