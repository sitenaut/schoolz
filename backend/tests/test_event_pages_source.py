from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest

from local_events.sources.base import RawEvent
from local_events.sources.event_pages import EventPageSource
from local_events.sources.theatre import TheatreSiteSource, to_raw_events

TODAY = date(2026, 10, 18)
TEXT = (
    "Holiday Parade - Saturday, November 28 beginning at 10 am. Boos and Brews: Join us Friday, October 10. "
    "Community Buy Nothing Exchange on May 17. " + "Bring gently used items to share with neighbors. " * 4
    + "Summer Bummer Fest: Sunday, June 20, 2027. "
    "Parade of Lights December 4, 2026, 6:30pm, Knight Park. Small Business Saturday"
)


def run(events):
    return to_raw_events(
        events, TEXT, source="cw", venue_name=None, venue_address=None, default_categories=["community"],
        page_url="https://town.example/events", today=TODAY, id_prefix="page", town="Collingswood, NJ",
    )


def titles(events):
    return [e.title for e in run(events)]


def test_a_written_weekday_must_match_the_date():
    # Boos and Brews' page is last year's: Oct 10, 2027 is a Sunday, not a Friday.
    assert titles([{"title": "Boos and Brews", "start_date": "2027-10-10", "weekday": "Friday", "year_written": False}]) == []
    assert titles([{"title": "Holiday Parade", "start_date": "2026-11-28", "weekday": "Saturday", "year_written": False}]) == ["Holiday Parade"]


def test_a_yearless_date_must_be_soon_whatever_the_model_says():
    # The model claimed the year was written; the page never says 2027.
    assert titles([{"title": "Community Buy Nothing Exchange", "start_date": "2027-05-17", "year_written": True}]) == []
    # A year the page does write is believed, however far off.
    assert titles([{"title": "Summer Bummer Fest", "start_date": "2027-06-20", "weekday": "Sunday", "year_written": True}]) == ["Summer Bummer Fest"]


def test_a_named_venue_is_placed_in_the_town():
    (ev,) = run([{"title": "Parade of Lights", "start_date": "2026-12-04", "start_time": "18:30", "venue": "Knight Park", "year_written": True}])
    assert ev.venue_name == "Knight Park" and ev.venue_address == "Knight Park, Collingswood, NJ"
    assert ev.source_event_id.startswith("page:") and not ev.all_day


def test_theatre_entries_without_the_new_fields_are_unaffected():
    (ev,) = to_raw_events(
        [{"title": "Holiday Parade", "start_date": "2027-11-28"}], TEXT, source="t", venue_name="Home", venue_address="1 Main",
        default_categories=["theatre"], page_url="https://x", today=TODAY,
    )
    assert ev.source_event_id.startswith("theatre:") and ev.venue_address == "1 Main"


@pytest.mark.anyio
async def test_the_same_event_on_two_pages_is_kept_once(monkeypatch):
    at = datetime(2026, 11, 28, 10, tzinfo=ZoneInfo("America/New_York"))

    async def both(self):
        return [
            RawEvent(source="cw", source_event_id="a", title="Holiday Parade", start_time=at),
            RawEvent(source="cw", source_event_id="b", title="2026 Collingswood Holiday Parade", start_time=at, venue_name="Haddon Avenue"),
            RawEvent(source="cw", source_event_id="c", title="Small Business Saturday", start_time=at),
        ]

    monkeypatch.setattr(TheatreSiteSource, "fetch", both)
    kept = await EventPageSource(name="cw", urls=["https://town.example"]).fetch()
    assert sorted(e.source_event_id for e in kept) == ["b", "c"]  # the copy naming a venue wins


@pytest.mark.anyio
async def test_a_page_read_once_is_not_paid_for_again_after_a_restart(monkeypatch):
    import uuid

    from local_events.sources import theatre

    calls = []

    class FakeMessages:
        async def create(self, **kwargs):
            calls.append(kwargs)
            block = type("B", (), {"type": "tool_use", "input": {"events": [{"title": "Holiday Parade", "start_date": "2026-11-28"}]}})()
            return type("R", (), {"content": [block], "stop_reason": "tool_use", "usage": None})()

    monkeypatch.setattr(theatre, "AsyncAnthropic", lambda **_: type("C", (), {"messages": FakeMessages()})())
    monkeypatch.setattr(theatre.observability, "record_llm_call", lambda *a, **k: None)
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(theatre, "_CACHE", {})
    src = EventPageSource(name="cw", urls=["https://town.example"])
    text = f"Holiday Parade, Saturday November 28 {uuid.uuid4()}"

    first = await src._extract(text)
    theatre._CACHE.clear()  # what a deploy does to the in-process cache
    second = await src._extract(text)
    assert first == second and len(calls) == 1


@pytest.mark.anyio
async def test_live_feed_posts_keep_events_honour_moves_and_ignore_the_posting_date(monkeypatch):
    from local_events.sources import thrillshare

    posts = [
        {"id": 3, "time": "2026-10-09T08:44:16-04:00", "status": "The Civic Association moved the Town Picnic to next Sunday, October 18th, 12 to 3 p.m."},
        {"id": 2, "time": "2026-10-06T10:48:57-04:00", "status": "Green Team Movie Night flyer attached"},
        {"id": 1, "time": "2026-10-06T10:22:45-04:00", "status": "<p>Oaklyn Town Picnic - Sunday, October 25 - 12 p.m. to 3 p.m.</p>"},
        {"id": 0, "time": "2026-10-05T09:00:00-04:00", "status": "PSE&G gas main work Monday 10/19 on Landis Ave, 7am to 5pm"},
    ]
    answers = {
        3: [{"title": "Town Picnic", "start_date": "2026-10-18", "start_time": "12:00", "weekday": "Sunday", "year_written": False, "moved_from": "2026-10-25"}],
        2: [{"title": "Green Team Movie Night", "start_date": "2026-10-06", "year_written": False}],
        1: [{"title": "Oaklyn Town Picnic", "start_date": "2026-10-25", "weekday": "Sunday", "year_written": False}],
        0: [],
    }

    class Resp:
        def __init__(self, page):
            self.page = page

        def raise_for_status(self):
            pass

        def json(self):
            return {"live_feeds": posts if self.page == 1 else []}

    class Client:
        def __init__(self, **_):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            pass

        async def get(self, url, params):
            return Resp(params["page_no"])

    async def extract(self, text):
        return next(answers[p["id"]] for p in posts if thrillshare.page_text(p["status"], "") in text)

    monkeypatch.setattr(thrillshare.httpx, "AsyncClient", Client)
    monkeypatch.setattr(EventPageSource, "_extract", extract)
    monkeypatch.setattr(thrillshare, "datetime", type("D", (datetime,), {"now": staticmethod(lambda tz=None: datetime(2026, 10, 12, 9, tzinfo=tz))}))
    src = thrillshare.ThrillshareSource("oaklyn", "1", site_url="https://oaklyn.example/", live_feed=True, location="Oaklyn, NJ")
    events = await src._live_feed()
    # Oct 25 was taken back by the later post; the movie night had no date of its own.
    assert [(e.title, e.start_time.date().isoformat()) for e in events] == [("Town Picnic", "2026-10-18")]
    assert events[0].url == "https://oaklyn.example/live-feed" and events[0].source_event_id.startswith("post:")
