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
