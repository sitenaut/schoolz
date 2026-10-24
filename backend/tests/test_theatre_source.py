import json
from datetime import date
from types import SimpleNamespace

import pytest

from local_events.sources import theatre
from local_events.sources.theatre import page_text, to_raw_events

TODAY = date(2026, 9, 27)
TEXT = (
    "Sweeney Todd - Oct 30-Nov 8 at Haddonfield Memorial High. Tickets [https://x.org/tix] Taylor Too Oct 25 7:00pm "
    "Crimson Theatre Tech Sept 28-30 Fall Show Cue-to-Cue Nov 20"
)


def run(prods, **kwargs):
    return to_raw_events(
        prods, TEXT, source="hp", venue_name="Home", venue_address="1 Main St",
        default_categories=["theatre"], page_url="https://x.org/season", today=TODAY, **kwargs,
    )


def test_run_range_is_all_day_with_end():
    (ev,) = run([{"title": "Sweeney Todd", "start_date": "2026-10-30", "end_date": "2026-11-08", "ticket_url": "https://x.org/tix"}])
    assert ev.all_day and ev.end_time.date() == date(2026, 11, 8)
    assert ev.url == "https://x.org/tix" and ev.venue_name == "Home"


def test_time_makes_it_timed_eastern():
    (ev,) = run([{"title": "Taylor Too", "start_date": "2026-10-25", "start_time": "19:00"}])
    assert not ev.all_day and ev.start_time.hour == 19 and ev.start_time.utcoffset().total_seconds() == -4 * 3600


def test_invented_title_and_invented_url_are_dropped():
    assert run([{"title": "Hamilton", "start_date": "2026-10-25"}]) == []
    (ev,) = run([{"title": "Taylor Too", "start_date": "2026-10-25", "ticket_url": "https://evil.example/"}])
    assert ev.url == "https://x.org/season"


def test_past_and_unparseable_dropped():
    assert run([{"title": "Taylor Too", "start_date": "2025-10-25"}, {"title": "Sweeney Todd", "start_date": "soon"}]) == []


def test_tech_and_cue_to_cue_are_never_shows_even_if_the_model_keeps_them():
    # Confirmed real: Haiku kept "Crimson Theatre Tech" as a production even
    # after the system prompt was told to skip tech days - the word
    # "Theatre" already in the title reads as a real show name to the model.
    assert run([{"title": "Crimson Theatre Tech", "start_date": "2026-09-28"}]) == []
    assert run([{"title": "Fall Show Cue-to-Cue", "start_date": "2026-11-20"}]) == []


def test_school_slug_passes_through_when_set():
    (ev,) = run([{"title": "Taylor Too", "start_date": "2026-10-25"}], school_slug="example-high")
    assert ev.school_slug == "example-high"
    (ev,) = run([{"title": "Taylor Too", "start_date": "2026-10-25"}])
    assert ev.school_slug is None


def test_page_text_inlines_links():
    assert "[https://x.org/a]" in page_text('<p>Show <a href="/a">Tickets</a></p>', "https://x.org")


@pytest.mark.anyio
async def test_an_unreadable_model_answer_is_never_kept_as_no_events(monkeypatch):
    answers, stored = [], {}

    class _Messages:
        async def create(self, **kwargs):
            return SimpleNamespace(content=answers.pop(0), stop_reason="tool_use", usage=None)

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    async def _stored(key):
        return stored.get(key)

    async def _store(key, items):
        stored[key] = items

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(theatre, "AsyncAnthropic", _Client)
    monkeypatch.setattr(theatre, "_stored", _stored)
    monkeypatch.setattr(theatre, "_store", _store)
    monkeypatch.setattr(theatre, "_CACHE", {})
    source = theatre.TheatreSiteSource("hp", ["https://x.org/season"])

    answers.append([SimpleNamespace(type="text", text="no tool call")])
    with pytest.raises(ValueError):
        await source._extract(TEXT)
    assert stored == {}

    # The list as a JSON string is the answer's real content, read and kept.
    show = {"title": "Sweeney Todd", "start_date": "2026-10-30"}
    answers.append([SimpleNamespace(type="tool_use", input={"productions": json.dumps([show])})])
    assert await source._extract(TEXT) == [show]
    assert list(stored.values()) == [[show]]
