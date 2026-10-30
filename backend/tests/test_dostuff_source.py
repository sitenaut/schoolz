import json
import re
from datetime import date
from pathlib import Path

import pytest

from local_events.prune import SOURCE_KEYS
from local_events.sources.dostuff import DoStuffSource, _devalue, has_next, parse_day, read_browse

# do215.com's `/events/live-music-events-philadelphia/2026/10/31/__data.json`, page 1 of 2.
FIXTURE = Path(__file__).parent / "fixtures" / "do215_music_day.json"
DAY = date(2026, 10, 31)
BASE = "https://do215.com"


def _browse():
    return read_browse(FIXTURE.read_text())


def _parse():
    return {e.title: e for e in parse_day(_browse(), "do215_music", BASE, DAY, ["music"])}


def test_the_night_before_carry_over_is_skipped():
    # Built To Spill starts Fri Oct 30, 8 pm and is listed again on Saturday's page.
    events = parse_day(_browse(), "do215_music", BASE, DAY)
    assert "Built To Spill" not in {e.title for e in events}
    # 20 on the page; the two Coltrane sets share a title, not a permalink.
    assert len({e.source_event_id for e in events}) == 19


def test_event_fields():
    ev = _parse()["Dracula's Ball ft. Lords of Acid"]
    assert ev.start_time.isoformat() == "2026-10-31T21:00:00-04:00"
    assert ev.venue_name == "Underground Arts"
    assert ev.venue_address is None
    assert ev.url == "https://do215.com/events/2026/10/31/dracula-s-ball-ft-lords-of-acid-tickets"
    assert ev.source_event_id == "/events/2026/10/31/dracula-s-ball-ft-lords-of-acid-tickets"
    assert ev.image_url.startswith("https://assets0.dostuffmedia.com/uploads/")
    assert ev.default_categories == ["music"]
    assert ev.raw["genres"] == ["Electronic / Dance", "Metal", "Rock"]


def test_paging_follows_has_next():
    assert has_next(_browse())
    assert not has_next({"_meta": {"has_next": False}})


def test_devalue_resolves_indices_and_constants():
    # {"a": [1, "x"], "b": undefined}
    assert _devalue([{"a": 1, "b": -1}, [2, 3], 1, "x"]) == {"a": [1, "x"], "b": None}


@pytest.mark.parametrize("text", [
    "<html><body><p>nothing here</p></body></html>",
    json.dumps({"type": "data", "nodes": [{"type": "data", "data": [{"layout": 1}, "x"]}]}),
])
def test_a_redesigned_page_raises_rather_than_reading_as_an_empty_day(text):
    with pytest.raises(ValueError):
        read_browse(text)


def test_category_is_a_path_not_a_query():
    # `?category=music` is ignored by the site and returns every kind of event.
    src = DoStuffSource("x", BASE + "/", category_path="/live-music-events-philadelphia/")
    assert src._url(DAY, 1) == "https://do215.com/events/live-music-events-philadelphia/2026/10/31/__data.json"
    assert src._url(DAY, 2).endswith("/2026/10/31/__data.json?page=2")


def test_prune_knows_every_source_list_the_pipeline_reads():
    pipeline = (Path(__file__).parent.parent / "local_events" / "pipeline.py").read_text()
    read = set(re.findall(r'params\.get\("(\w+_sources)"\)', pipeline))
    assert "dostuff_sources" in read and read <= set(SOURCE_KEYS), sorted(read - set(SOURCE_KEYS))
