import re
from datetime import date
from pathlib import Path

import pytest

from local_events.prune import SOURCE_KEYS
from local_events.sources.dostuff import DoStuffSource, parse_day

FIXTURE = Path(__file__).parent / "fixtures" / "do215_music_day.html"
DAY = date(2026, 10, 9)
BASE = "https://do215.com"


def _parse(**kw):
    return {e.title: e for e in parse_day(FIXTURE.read_text(), "do215_music", BASE, DAY, ["music"], **kw)}


def test_multi_day_carry_overs_and_cards_without_a_start_are_skipped():
    assert set(_parse()) == {"Chelsea Wolfe", "DECIDE TODAY, BASECK"}


def test_event_fields():
    ev = _parse()["Chelsea Wolfe"]
    assert ev.start_time.isoformat() == "2026-10-09T20:30:00-04:00"
    assert ev.venue_name == "Keswick Theatre"
    assert ev.venue_address == "291 N Keswick Ave, Glenside, PA 19038"
    assert ev.url == "https://do215.com/events/2026/10/9/chelsea-wolfe-tickets"
    assert ev.source_event_id == "/events/2026/10/9/chelsea-wolfe-tickets"
    assert ev.image_url == "https://assets0.dostuffmedia.com/uploads/x.jpg"
    assert ev.default_categories == ["music"]
    assert ev.raw["ticket_url"].startswith("https://www.axs.com/")


def test_address_already_typed_into_the_street_is_not_repeated():
    assert _parse()["DECIDE TODAY, BASECK"].venue_address == "304 South St, Philadelphia, PA 19147"


def test_a_redesigned_page_raises_rather_than_reading_as_an_empty_day():
    with pytest.raises(ValueError):
        parse_day("<html><body><p>nothing here</p></body></html>", "x", BASE, DAY)


def test_category_is_a_path_not_a_query():
    # `?category=music` is ignored by the site and returns every kind of event.
    src = DoStuffSource("x", BASE + "/", category_path="/live-music-events-philadelphia/")
    assert src._url(DAY, 1) == "https://do215.com/events/live-music-events-philadelphia/2026/10/09"
    assert src._url(DAY, 2).endswith("/2026/10/09?page=2")


def test_prune_knows_every_source_list_the_pipeline_reads():
    pipeline = (Path(__file__).parent.parent / "local_events" / "pipeline.py").read_text()
    read = set(re.findall(r'params\.get\("(\w+_sources)"\)', pipeline))
    assert "dostuff_sources" in read and read <= set(SOURCE_KEYS), sorted(read - set(SOURCE_KEYS))
