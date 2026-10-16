"""Town and county calendars: the meeting filter, Revize's old calendar_app,
and Apptegy (Thrillshare) town sites."""
import uuid
from datetime import UTC, date, datetime, timedelta
from functools import partial

import httpx
import pytest

from local_events import filters
from local_events.filters import apply_filters, filters_by_source, is_excluded
from local_events.sources import revize_calendar_app, thrillshare
from local_events.sources.base import RawEvent, Source
from local_events.sources.revize_calendar_app import RevizeCalendarAppSource, parse_month

ET = revize_calendar_app._ET


# Titles copied from the real feeds (Cinnaminson, Maple Shade, Medford,
# Oaklyn, Mount Ephraim, Cherry Hill, Washington Twp).
MEETINGS = [
    "Township Committee Regular Meeting",
    "Planning Board Meeting has been cancelled",
    "Township Committee Work Session ",
    "Zoning Board of Adjustment Meeting",
    "Site Plan/Subdivision Review Meeting",
    "Caucus Meeting",
    "Oaklyn Council Meeting (Close out meeting)",
    "Oaklyn Green Team meeting",
    "Maple Shade Court",
    "Municipal Court",
    "Moorestown Day Court",
    "Reorganization Meeting",
]
KEPT = [
    "Municipal Offices Closed for Thanksgiving",
    "Winter Festival",
    "Shred Event",
    "Community Tree Plantings - Bunker Hill Trails",
    "Town Hall Meeting with the Mayor",
    "Kindergarten Information Session",
    "Basketball Courtside Clinic",
    "Brush Collection - Section 2",
]


@pytest.mark.parametrize("title", MEETINGS)
def test_skip_meetings_drops_the_towns_own_business(title):
    assert is_excluded(title, [filters.MEETING_PATTERN])


@pytest.mark.parametrize("title", KEPT)
def test_skip_meetings_keeps_what_a_family_would_go_to(title):
    assert not is_excluded(title, [filters.MEETING_PATTERN])


def _raw(title, source="town"):
    return RawEvent(source=source, source_event_id=uuid.uuid4().hex, title=title, start_time=datetime.now(UTC))


def test_filters_are_per_entry_and_work_for_any_source_type():
    params = {
        "ical_sources": [{"name": "town", "url": "x", "skip_meetings": True, "exclude_title_patterns": [r"^R\d+ \d+ \d+-\d+$"]}],
        "tribe_sources": [{"name": "library", "base_url": "x"}],
        "thrillshare_sources": [{"name": "boro", "org_id": "1", "exclude_title_patterns": ["[unclosed"]}],
    }
    by_source = filters_by_source(params)
    assert set(by_source) == {"town"}  # a bad regex is skipped, not fatal
    kept, dropped = apply_filters([_raw("Council Meeting"), _raw("R1 760 8-4"), _raw("Fall Festival")], by_source["town"])
    assert [r.title for r in kept] == ["Fall Festival"] and dropped == 2
    unfiltered = [_raw("Council Meeting")]
    assert apply_filters(unfiltered, None) == (unfiltered, 0)


class _FakeSource(Source):
    def __init__(self, name, raws):
        self.name = name
        self.raws = raws
        self.partial_failures = []

    async def fetch(self):
        return self.raws


@pytest.mark.anyio
async def test_pipeline_filters_and_deletes_meetings_it_had_already_stored(monkeypatch):
    from sqlalchemy import select

    import database
    from local_events import pipeline
    from models import LocalEvent

    name = f"town-{uuid.uuid4().hex[:8]}"
    soon = datetime.now(UTC) + timedelta(days=3)
    async with database.SessionLocal() as db:
        # Stored by an earlier run, before skip_meetings was set.
        db.add(LocalEvent(source=name, source_event_id="old-meeting", title="Planning Board Meeting", start_time=soon, categories=[]))
        await db.flush()
        raws = [
            RawEvent(source=name, source_event_id="m", title="Township Council Meeting", start_time=soon),
            RawEvent(source=name, source_event_id="f", title=f"Winter Festival {name}", start_time=soon),
        ]
        monkeypatch.setattr(pipeline, "_build_sources", lambda params: [_FakeSource(name, raws)])
        summary = await pipeline.run_pipeline(db, {"ical_sources": [{"name": name, "url": "x", "skip_meetings": True}]})
        titles = set((await db.execute(select(LocalEvent.title).where(LocalEvent.source == name))).scalars())
    assert titles == {f"Winter Festival {name}"}
    assert summary["per_source"][name] == 1
    assert summary["excluded"][name] == 2


MONTH_XML = """<?xml version="1.0" encoding="utf-8"?>


<events format="3.2" version="09-02-2014" published="10-13-2026 11:09 AM">
  <event id="1465" calendarid="1">
    <name><![CDATA[Collingswood Farmers' Market]]></name>
    <date_begin>May 2, 2026</date_begin>
    <date_end>Nov 21, 2026</date_end>
    <time_begin>8:00</time_begin>
    <duration>4hrs</duration>
    <repeat>weekly</repeat>
    <dates>10-10-2026,10-17-2026,10-24-2026</dates>
    <detail><![CDATA[<font size="2">Under the <b>PATCO</b> line,&nbsp;rain or shine.</font>]]></detail>
  </event>
  <event id="186" calendarid="1">
    <name>October brush collection</name>
    <event_location>Southampton, NJ</event_location>
    <date_begin>Oct 11, 2026</date_begin>
    <date_end>Oct 16, 2026</date_end>
    <time_begin></time_begin>
    <duration>6days</duration>
    <dates>10-11-2026,10-12-2026+,10-13-2026+,10-14-2026+,10-15-2026+,10-16-2026+</dates>
    <detail />
  </event>
  <event id="1474" calendarid="1">
    <name>The Rascals</name>
    <date_begin>Oct 17, 2026</date_begin>
    <date_end>Oct 17, 2026</date_end>
    <time_begin>19:00</time_begin>
    <duration></duration>
    <dates></dates>
  </event>
  <event id="0" calendarid="1"><name>Placeholder</name><date_begin>Oct 1, 2026</date_begin></event>
</events>
"""


def test_revize_month_file_expands_repeats_and_skips_continuation_days():
    events = parse_month(MONTH_XML, source="collingswood", base_url="https://collingswood.com/", default_categories=["collingswood"], venue_name=None, venue_address=None)
    market = [e for e in events if e.title == "Collingswood Farmers' Market"]
    assert [e.start_time for e in market] == [datetime(2026, 10, d, 8, 0, tzinfo=ET) for d in (10, 17, 24)]
    assert market[0].end_time == datetime(2026, 10, 10, 12, 0, tzinfo=ET)
    assert market[0].description == "Under the PATCO line, rain or shine."
    assert market[0].source_event_id == "1465:2026-10-10"
    assert market[0].url == "https://collingswood.com/calendar.php"

    (brush,) = [e for e in events if e.title == "October brush collection"]
    assert brush.all_day and brush.start_time == datetime(2026, 10, 11, tzinfo=ET)
    assert brush.end_time == datetime(2026, 10, 17, tzinfo=ET)
    assert brush.venue_name == "Southampton, NJ"

    (show,) = [e for e in events if e.title == "The Rascals"]
    assert show.start_time == datetime(2026, 10, 17, 19, 0, tzinfo=ET) and show.end_time is None and not show.all_day
    assert "Placeholder" not in {e.title for e in events}  # id 0 is the app's empty row


def _mock(monkeypatch, handler):
    monkeypatch.setattr(revize_calendar_app.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))


def _freeze(monkeypatch, today):
    class _Frozen(datetime):
        @classmethod
        def now(cls, tz=None):
            return datetime(today.year, today.month, today.day, 9, tzinfo=tz)

    monkeypatch.setattr(revize_calendar_app, "datetime", _Frozen)


@pytest.mark.anyio
async def test_revize_source_reads_each_month_and_dedupes_a_repeat_listed_in_both(monkeypatch):
    _freeze(monkeypatch, date(2026, 10, 15))
    seen = []

    def handler(request):
        seen.append(request.url.path)
        if request.url.path.endswith("calendar_db_data.xml"):
            return httpx.Response(200, text="<calendar_data />")
        if request.url.path.endswith("_2026-10.xml") or request.url.path.endswith("_2026-11.xml"):
            return httpx.Response(200, text=MONTH_XML)  # the market repeats in both files
        return httpx.Response(404, text="<html>404</html>")

    _mock(monkeypatch, handler)
    events = await RevizeCalendarAppSource("collingswood", "https://collingswood.com", months_ahead=2).fetch()
    assert "/calendar_app/db/calendar_1_activemonthsdata_2026-12.xml" in seen
    ids = [e.source_event_id for e in events]
    assert len(ids) == len(set(ids))
    # Oct 10 is before "today"; the brush collection runs through the 16th, so it stays.
    assert "1465:2026-10-10" not in ids and "1465:2026-10-17" in ids and "186:2026-10-11" in ids


@pytest.mark.anyio
async def test_revize_source_raises_when_the_site_no_longer_has_the_app(monkeypatch):
    _mock(monkeypatch, lambda request: httpx.Response(404, text="gone"))
    with pytest.raises(httpx.HTTPStatusError):
        await RevizeCalendarAppSource("gone", "https://example.org").fetch()


@pytest.mark.anyio
async def test_revize_source_reports_a_broken_month_without_losing_the_rest(monkeypatch):
    _freeze(monkeypatch, date(2026, 10, 15))

    def handler(request):
        if request.url.path.endswith("calendar_db_data.xml"):
            return httpx.Response(200, text="<calendar_data />")
        if request.url.path.endswith("_2026-10.xml"):
            return httpx.Response(200, text=MONTH_XML)
        return httpx.Response(200, text="<events><event id='1'><name>x</name></events>")  # mismatched tag, seen for real

    _mock(monkeypatch, handler)
    source = RevizeCalendarAppSource("southampton", "https://www.southamptonnj.org", months_ahead=1)
    events = await source.fetch()
    assert events and source.partial_failures and "bad XML" in source.partial_failures[0]


@pytest.mark.anyio
async def test_thrillshare_town_source_keeps_venue_and_pin(monkeypatch):
    def handler(request):
        assert request.url.path == "/api/v4/o/25480/cms/events"
        return httpx.Response(200, json={"events": [{
            "id": 37238982, "title": "Townwide Fall Tree Planting", "description": "",
            "venue": "Oaklyn Borough Hall, 500 White Horse Pike, Oaklyn, NJ 08107,",
            "start_at": "2026-10-24T09:00:00.000-04:00", "end_at": "2026-10-24T12:00:00.000-04:00",
            "all_day": False, "latitude": "39.9034686", "longitude": "",
        }]})

    from services import apptegy
    monkeypatch.setattr(apptegy.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    (event,) = await thrillshare.ThrillshareSource("oaklyn_borough", "25480", site_url="https://www.oaklyn-nj.net/", default_categories=["oaklyn", "municipal"]).fetch()
    assert event.venue_name == "Oaklyn Borough Hall, 500 White Horse Pike, Oaklyn, NJ 08107"
    assert event.latitude == pytest.approx(39.9034686) and event.longitude is None
    assert event.url == "https://www.oaklyn-nj.net/" and event.source_event_id == "37238982" and not event.all_day


@pytest.mark.anyio
async def test_json_upcoming_only_drops_a_revize_towns_history(monkeypatch):
    from local_events.sources import json_api

    soon = (datetime.now(UTC) + timedelta(days=5)).strftime("%Y-%m-%dT%H:%M:%S")
    rows = [
        {"id": 1, "title": "Pumpkin Fest", "start": soon, "end": soon},
        {"id": 2, "title": "Website review", "start": "2019-03-01T10:00:00", "end": "2019-03-01T11:00:00"},
    ]
    monkeypatch.setattr(json_api.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(lambda r: httpx.Response(200, json=rows))))
    source = json_api.JsonApiSource("national_park_borough", "https://www.nationalparknj.com/x", data_path="", upcoming_only=True)
    assert [e.title for e in await source.fetch()] == ["Pumpkin Fest"]
    source.upcoming_only = False
    assert len(await source.fetch()) == 2
