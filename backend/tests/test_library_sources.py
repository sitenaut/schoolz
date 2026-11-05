"""Library calendar adapters: LibCal, BiblioCommons, Modern Events Calendar,
Drupal FullCalendar, plus the venue/scraper options added to tribe, iCal and RSS."""
import html
import json
from datetime import UTC, datetime, timedelta
from functools import partial
from zoneinfo import ZoneInfo

import httpx
import pytest

from local_events.sources import bibliocommons, drupal_fullcalendar, ical, libcal, mec, rss
from local_events.sources.bibliocommons import BiblioCommonsSource
from local_events.sources.drupal_fullcalendar import DrupalFullCalendarSource
from local_events.sources.ical import ICalSource
from local_events.sources.libcal import LibCalSource
from local_events.sources.mec import MECSource, parse_events_side
from local_events.sources.tribe import TribeEventsSource

ET = ZoneInfo("America/New_York")


def _soon(days=3, hour=10):
    return (datetime.now(ET) + timedelta(days=days)).replace(hour=hour, minute=0, second=0, microsecond=0)


def _mock(module, handler):
    return partial(httpx.AsyncClient, transport=httpx.MockTransport(handler))


@pytest.mark.anyio
async def test_libcal_pages_keeps_upcoming_and_names_the_room(monkeypatch):
    soon, later, past = _soon(2), _soon(200), _soon(-5)
    rows = [
        {"id": 1, "title": "Story &amp; Craft", "description": "<p>Fun</p>", "startdt": soon.strftime("%Y-%m-%d %H:%M:%S"),
         "enddt": (soon + timedelta(hours=1)).strftime("%Y-%m-%d %H:%M:%S"), "all_day": False, "location": "Meeting Room A",
         "url": "https://x.test/event/1"},
        {"id": 2, "title": "Far future", "startdt": later.strftime("%Y-%m-%d %H:%M:%S"), "enddt": later.strftime("%Y-%m-%d %H:%M:%S")},
        {"id": 3, "title": "Over", "startdt": past.strftime("%Y-%m-%d %H:%M:%S"), "enddt": past.strftime("%Y-%m-%d %H:%M:%S")},
    ]
    seen = []

    def handler(request):
        seen.append(dict(request.url.params))
        return httpx.Response(200, json={"total_results": 3, "results": rows})

    monkeypatch.setattr(libcal.httpx, "AsyncClient", _mock(libcal, handler))
    events = await LibCalSource("lib", "https://x.test", venue_name="The Library", venue_address="1 Main St", days_ahead=30).fetch()

    assert seen[0]["date"] == "0000-00-00" and seen[0]["c"] == "-1"
    assert [e.title for e in events] == ["Story & Craft"]
    e = events[0]
    assert e.source_event_id.startswith("1:") and e.venue_name == "The Library"
    assert e.venue_address == "Meeting Room A, 1 Main St"
    assert e.start_time.tzinfo is not None and e.end_time > e.start_time


@pytest.mark.anyio
async def test_bibliocommons_filters_branches_and_cancelled(monkeypatch):
    soon = _soon(1).strftime("%Y-%m-%dT%H:%M")
    payload = {
        "events": {"items": ["a", "b", "c"], "pagination": {"pages": 1}},
        "entities": {
            "events": {
                "a": {"id": "a", "definition": {"start": soon, "end": soon, "title": "Chess", "branchLocationId": "5", "locationDetails": "Room 2", "description": "<p>x</p>"}},
                "b": {"id": "b", "definition": {"start": soon, "title": "Elsewhere", "branchLocationId": "3"}},
                "c": {"id": "c", "definition": {"start": soon, "title": "Called off", "branchLocationId": "5", "isCancelled": True}},
            },
            "locations": {
                "5": {"id": "5", "name": "Cinnaminson Library", "address": {"number": "1619", "street": "Riverton Road", "city": "Cinnaminson", "state": "NJ", "zip": "08077"}},
                "3": {"id": "3", "name": "Burlington County Library", "address": {}},
            },
            "eventTypes": {},
        },
    }
    monkeypatch.setattr(bibliocommons.httpx, "AsyncClient", _mock(bibliocommons, lambda r: httpx.Response(200, json=payload)))
    events = await BiblioCommonsSource("bc", "bclsnj", branches=["cinnaminson library"]).fetch()

    assert [e.title for e in events] == ["Chess"]
    assert events[0].venue_name == "Cinnaminson Library"
    assert events[0].venue_address == "Room 2, 1619 Riverton Road, Cinnaminson, NJ 08077"
    assert events[0].url == "https://bclsnj.bibliocommons.com/events/a"


def _mec_block(cell, name, url, time_text):
    ld = json.dumps({"@type": "Event", "name": name, "startDate": cell, "url": url, "description": "Join &lt;b&gt;us&lt;/b&gt;",
                     "location": {"@type": "Place", "name": "Community Room", "address": "The Library"}})
    return (f'<div class="mec-calendar-events-sec"  data-mec-cell="{cell.replace("-", "")}" ><script type="application/ld+json">{ld}</script>'
            f'<article class="mec-event-article"><div class="mec-event-time mec-color"><i class="mec-sl-clock-o"></i> {time_text}</div></article></div>')


def test_mec_reads_time_from_the_article_not_the_date_only_jsonld():
    markup = (_mec_block("2026-11-03", "Crochet Basics", "https://x.test/events/crochet/", "5:00 pm - 6:30 pm")
              + _mec_block("2026-11-04", "Book Sale", "https://x.test/events/sale/", "All Day"))
    timed, undated = parse_events_side(markup, "coll", ["library"])

    assert timed.start_time.isoformat() == "2026-11-03T17:00:00-05:00"
    assert timed.end_time.isoformat() == "2026-11-03T18:30:00-05:00"
    assert timed.venue_name == "Community Room" and timed.description == "Join us"
    assert undated.all_day is True and undated.default_categories == ["library"]


@pytest.mark.anyio
async def test_mec_fetch_posts_each_month_and_dedups_padding_days(monkeypatch):
    today = datetime.now(ET).date()
    cell = (today + timedelta(days=1)).isoformat()
    page = '<div id="mec_skin_77"></div><script>var ajaxurl = "https://x.test/wp-admin/admin-ajax.php";</script>'
    posts = []

    def handler(request):
        if request.method == "GET":
            return httpx.Response(200, text=page)
        posts.append(request.content.decode())
        return httpx.Response(200, json={"events_side": _mec_block(cell, "Same event", "https://x.test/e/", "9:00 am")})

    monkeypatch.setattr(mec.httpx, "AsyncClient", _mock(mec, handler))
    events = await MECSource("coll", "https://x.test/cal/", months_ahead=2).fetch()

    assert len(posts) == 3 and "id=77" in posts[0] and "action=mec_monthly_view_load_month" in posts[0]
    assert len(events) == 1  # the same day padded into three month grids


@pytest.mark.anyio
async def test_drupal_fullcalendar_reads_embedded_events(monkeypatch):
    soon = _soon(4)
    events = [
        {"title": '<a href="/node/1">Wee Readers</a>', "eid": "1", "url": "/node/1", "start": soon.strftime("%Y-%m-%d"), "allDay": True},
        {"title": '<a href="/node/2">Timed &amp; Fun</a>', "eid": "2", "url": "/node/2", "start": soon.strftime("%Y-%m-%dT10:15:00"), "allDay": False},
        {"title": '<a href="/node/3">Ancient</a>', "eid": "3", "url": "/node/3", "start": "2020-05-19", "allDay": True},
    ]
    settings = {"fullCalendarView": [{"calendar_options": json.dumps({"events": events})}]}
    page = f'<script type="application/json" data-drupal-selector="drupal-settings-json">{json.dumps(settings)}</script>'
    monkeypatch.setattr(drupal_fullcalendar.httpx, "AsyncClient", _mock(drupal_fullcalendar, lambda r: httpx.Response(200, text=page)))
    got = await DrupalFullCalendarSource("pen", "https://lib.test/events", venue_name="Pennsauken Library").fetch()

    assert [e.title for e in got] == ["Wee Readers", "Timed & Fun"]
    assert got[0].all_day is True and got[1].all_day is False and got[1].start_time.hour == 10
    assert got[0].url == "https://lib.test/node/1" and got[0].venue_name == "Pennsauken Library"


@pytest.mark.anyio
async def test_ical_venue_override_and_upcoming_only(monkeypatch):
    soon, past = _soon(2), _soon(-400)
    fmt = "%Y%m%dT%H%M%S"
    feed = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        f"BEGIN:VEVENT\r\nUID:a\r\nSUMMARY:Upcoming\r\nDTSTART:{soon.strftime(fmt)}\r\nLOCATION:US\r\nEND:VEVENT\r\n"
        f"BEGIN:VEVENT\r\nUID:b\r\nSUMMARY:Old\r\nDTSTART:{past.strftime(fmt)}\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    monkeypatch.setattr(ical.httpx, "AsyncClient", _mock(ical, lambda r: httpx.Response(200, content=feed.encode())))
    kept = await ICalSource("lib", "https://x.test/f.ics", venue_name="Haddonfield Public Library", upcoming_only=True).fetch()
    everything = await ICalSource("lib", "https://x.test/f.ics").fetch()

    assert [e.title for e in kept] == ["Upcoming"] and kept[0].venue_name == "Haddonfield Public Library"
    assert len(everything) == 2 and everything[0].venue_name == "US"


@pytest.mark.anyio
async def test_ical_location_drops_drupals_country_and_map_link(monkeypatch):
    """Gloucester City's Drupal 7 export puts the whole rendered address block
    in LOCATION, as escaped newlines."""
    soon = _soon(2).strftime("%Y%m%dT%H%M%S")
    feed = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        f"BEGIN:VEVENT\r\nUID:a\r\nSUMMARY:Fishing Derby\r\nDTSTART:{soon}\r\n"
        "LOCATION:Martin's Lake\\n                              \\nUnited States\\n      \\n\\n      \\nSee map: Google Maps\r\nEND:VEVENT\r\n"
        f"BEGIN:VEVENT\r\nUID:b\r\nSUMMARY:Shred Event\r\nDTSTART:{soon}\r\n"
        "LOCATION:Courthouse\\n313 Monmouth Street\\nGloucester City\\, NJ 08030\\nUnited States\\nSee map: Google Maps\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    monkeypatch.setattr(ical.httpx, "AsyncClient", _mock(ical, lambda r: httpx.Response(200, content=feed.encode())))
    events = await ICalSource("town", "https://x.test/export.ics").fetch()

    assert [e.venue_name for e in events] == ["Martin's Lake", "Courthouse, 313 Monmouth Street, Gloucester City, NJ 08030"]


@pytest.mark.anyio
async def test_ical_decodes_civicplus_hcms_entities_and_drops_its_field_label(monkeypatch):
    """Eastampton's CivicPlus HCMS export escapes its HTML and opens each
    description with the field's label on a line of its own."""
    soon = _soon(2).strftime("%Y%m%dT%H%M%S")
    feed = (
        "BEGIN:VCALENDAR\r\nVERSION:2.0\r\n"
        f"BEGIN:VEVENT\r\nUID:a\r\nSUMMARY:Trunk-or-Treat &amp; Bonfire 10/24\r\nDTSTART:{soon}\r\n"
        "DESCRIPTION:Body \\n\\nCandy &amp; a bonfire at Smithville Park.\\n \r\nEND:VEVENT\r\n"
        f"BEGIN:VEVENT\r\nUID:b\r\nSUMMARY:Q&A Night\r\nDTSTART:{soon}\r\n"
        "DESCRIPTION:Description of the route and parking.\r\nEND:VEVENT\r\n"
        "END:VCALENDAR\r\n"
    )
    monkeypatch.setattr(ical.httpx, "AsyncClient", _mock(ical, lambda r: httpx.Response(200, content=feed.encode())))
    events = await ICalSource("town", "https://x.test/calendar.ics").fetch()

    assert [(e.title, e.description) for e in events] == [
        ("Trunk-or-Treat & Bonfire 10/24", "Candy & a bonfire at Smithville Park."),
        ("Q&A Night", "Description of the route and parking."),
    ]


@pytest.mark.anyio
async def test_rss_via_scraper_reads_the_feed_out_of_chromiums_text_viewer(monkeypatch):
    """Fieldsboro's Cloudflare answers plain HTTP with a challenge. Through a
    scraper the feed comes back as the page Chromium shows for it: the XML
    escaped inside a <pre>."""
    feed = (
        '<?xml version="1.0" encoding="utf-8"?><rss version="2.0"><channel><title>Upcoming Events Feed</title>'
        "<item><title>Annual Christmas Tree Lighting</title><link>https://town.test/community/page/tree-lighting</link>"
        # Its HTML escaped twice, as Fieldsboro's is.
        '<description>&amp;lt;div dir="auto"&amp;gt;Join us&amp;amp;nbsp;at Town Hall&amp;lt;/div&amp;gt;</description>'
        '<pubDate>Sun, 29 Nov 2026 17:30:00 -0500</pubDate><guid isPermaLink="false">abc.0</guid></item>'
        "</channel></rss>"
    )
    viewer = f'<html><head><meta name="color-scheme" content="light dark"></head><body><pre style="word-wrap: break-word;">{html.escape(feed)}</pre></body></html>'
    calls = []

    async def fake_raw(url, timeout=90.0, prefer_residential=False):
        calls.append((url, prefer_residential))
        return viewer

    monkeypatch.setattr(rss, "fetch_raw_via_scraper", fake_raw)
    src = rss.RSSSource("town", "https://town.test/calendar/rss", treat_pubdate_as_start=True, via_scraper=True, prefer_residential=True)
    events = await src.fetch()

    assert calls == [("https://town.test/calendar/rss", True)]
    assert [(e.title, e.start_time) for e in events] == [("Annual Christmas Tree Lighting", datetime(2026, 11, 29, 22, 30, tzinfo=UTC))]
    assert " ".join(events[0].description.split()) == "Join us at Town Hall"
    # A feed that arrives as itself (a download, or plain HTTP) is left alone.
    assert rss._unwrap_text_viewer(feed) == feed


@pytest.mark.anyio
async def test_raw_fetch_asks_every_scraper_for_stealth_off(monkeypatch):
    """The least evasive fetch first: the Pi gets past these feeds' Cloudflare
    without playwright-stealth, so no scraper is asked to run it."""
    from local_events.sources import scraper

    sent = []

    def handler(request):
        sent.append((request.url.host, json.loads(request.content)))
        if request.url.host == "pi.test":
            return httpx.Response(200, json={"body": "<html><title>Just a moment...</title></html>"})
        return httpx.Response(200, json={"body": "BEGIN:VCALENDAR"})

    real_client = httpx.AsyncClient
    monkeypatch.setattr(scraper.httpx, "AsyncClient", lambda **kw: real_client(transport=httpx.MockTransport(handler)))
    monkeypatch.setenv("RESIDENTIAL_SCRAPER_URL", "https://pi.test")
    monkeypatch.setenv("LOCAL_EVENTS_SCRAPER_URL", "https://droplet.test")
    monkeypatch.setenv("LOCAL_EVENTS_SCRAPER_KEY", "k")
    monkeypatch.delenv("SCRAPER_URL", raising=False)

    body = await scraper.fetch_raw_via_scraper("https://town.test/calendar.ics", prefer_residential=True)

    assert body == "BEGIN:VCALENDAR"
    asked = {"url": "https://town.test/calendar.ics", "stealth": False}
    assert sent == [("pi.test", asked), ("droplet.test", asked)]


@pytest.mark.anyio
async def test_tribe_via_scraper_reads_json_and_falls_back_to_library_venue(monkeypatch):
    soon = _soon(2).strftime("%Y-%m-%d %H:%M:%S")
    body = json.dumps({"events": [{"id": 9, "title": "Story Time", "status": "publish", "start_date": soon, "end_date": soon,
                                   "venue": [], "categories": []}], "next_rest_url": None})
    calls = []

    async def fake_render(url, **kwargs):
        calls.append(url)
        if len(calls) == 1:  # first try lands on Cloudflare's HTML 403
            return "<html><head><title>403 - Forbidden</title></head><body>Forbidden</body></html>", url
        return f"<html><body><pre>{body}</pre></body></html>", url

    import local_events.sources.scraper as scraper_mod
    monkeypatch.setattr(scraper_mod, "fetch_rendered_html", fake_render)
    src = TribeEventsSource("run", "https://lib.test", via_scraper=True, venue_name="Runnemede Library", venue_address="2 Broadway")
    events = await src.fetch()

    assert len(calls) == 2 and "/wp-json/tribe/events/v1/events" in calls[0] and "per_page=50" in calls[0]
    assert events[0].venue_name == "Runnemede Library" and events[0].venue_address == "2 Broadway"
