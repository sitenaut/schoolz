import json
from datetime import date, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest

from local_events.prune import SOURCE_KEYS
from local_events.sources.runsignup import parse_races

FIXTURE = Path(__file__).parent / "fixtures" / "runsignup_races.json"
ET = ZoneInfo("America/New_York")
TODAY = date(2026, 10, 6)


def _parse(**kwargs):
    kwargs.setdefault("today", TODAY)
    return {e.title: e for e in parse_races(json.loads(FIXTURE.read_text()), "runsignup", **kwargs)}


def test_a_race_is_one_event_with_its_distances_time_and_price():
    race = _parse(default_categories=["sports"])["BookSmiles 5K & 1 Mile Walk for Literacy"]
    assert race.start_time == datetime(2026, 10, 11, 9, 0, tzinfo=ET)
    assert race.end_time == datetime(2026, 10, 11, 11, 0, tzinfo=ET)
    assert not race.all_day
    assert race.source_event_id == "146264-20261011"
    assert race.url == "https://runsignup.com/Race/NJ/CherryHill/BookSmiles5K"
    assert race.venue_address == "510 Park Blvd, Cherry Hill, NJ 08002"
    assert race.description.startswith("5K, 1 Miles. Flat and fast") and "<p>" not in race.description
    assert race.price_min == race.price_max == 35.0 and race.is_free is False
    assert race.default_categories == ["sports"]


def test_virtual_races_clubs_and_season_signups_are_skipped():
    events = _parse()
    # A virtual-only race, a club membership filed as a virtual race, and a
    # cheer season filed as event_type "other".
    assert "We Love Teachers 5K - Philadelphia" not in events
    assert "Cinnaminson Running Club" not in events
    assert "St. Charles Cheer" not in events
    # Its only event was in 2021 (with an end date in 2121).
    assert not any(title.startswith("Ninja Warrior") for title in events)


def test_the_date_comes_from_the_in_person_events_not_the_virtual_week():
    # The virtual 5K opens 10/11; the run at the venue is 10/18, with no time given.
    race = _parse()["WXPN 5K Run for Musicians On Call"]
    assert race.all_day and race.start_time.date() == date(2026, 10, 18)
    assert race.end_time is None


def test_a_series_last_leg_is_not_the_first_days_end_time():
    series = next(e for title, e in _parse().items() if title.startswith("Healthy Kids Running Series"))
    assert series.start_time == datetime(2026, 10, 11, 10, 30, tzinfo=ET)
    assert series.end_time is None
    # A 48-hour race really does end two mornings later.
    endurance = _parse()["Hainesport Endurance Run"]
    assert endurance.start_time == datetime(2026, 10, 10, 9, 0, tzinfo=ET)
    assert endurance.end_time == datetime(2026, 10, 12, 9, 0, tzinfo=ET)


def test_a_race_with_no_next_date_is_still_found_by_its_events_once_in_the_window():
    title = "Winter Thaw Out Race Series"
    assert title not in _parse(days_ahead=120)
    assert _parse(days_ahead=180)[title].start_time == datetime(2027, 2, 28, 9, 0, tzinfo=ET)


def test_exclude_patterns_and_states_filter():
    mill = "Cookie Run 5K/10K/13.1 NEW JERSEY"
    assert mill in _parse()
    assert mill not in _parse(exclude_patterns=["course map will be emailed"])
    assert all(", NJ " in e.venue_address for e in _parse(states=["nj"]).values())
    assert "WXPN 5K Run for Musicians On Call" not in _parse(states=["NJ"])


def test_a_response_without_races_raises_instead_of_returning_nothing():
    with pytest.raises(ValueError):
        parse_races({"error": {"error_code": 6}}, "runsignup", today=TODAY)


def test_prune_knows_runsignup_sources():
    assert "runsignup_sources" in SOURCE_KEYS
