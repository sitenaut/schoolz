import re
from pathlib import Path

import pytest

from local_events.prune import SOURCE_KEYS
from local_events.sources.patch import parse_region, region_events

FIXTURE = Path(__file__).parent / "fixtures" / "patch_cherryhill_calendar.html"
CENTER = (39.85, -74.98)


def _parse(**kw):
    return parse_region(FIXTURE.read_text(), "patch", center=CENTER, max_miles=15, default_categories=["patch"], **kw)


def test_thin_aggregator_rows_and_multi_day_duplicates_are_not_events():
    events = region_events(FIXTURE.read_text())
    ids = [str(e["id"]) for e in events]
    assert len(ids) == len(set(ids)) == 16
    assert "14422472" not in ids  # patchAmFreeEvent: no displayDate, no link


def test_statewide_promotions_and_online_webinars_are_dropped_by_radius():
    titles = {e.title for e in _parse()}
    assert "Estate Planning: 5 Essential Things You Should Know" not in titles  # Paramus webinar, no coords
    assert "The Race Of Gentlemen Sat & Sun Oct. 3 & 4, 2026" not in titles  # Wildwood
    assert "Four Quarters FREE Family Trunk or Treat 2026" in titles
    # 4th Annual Oktoberfest at The Red Barn Farm (Hammonton) is ~16.5 miles out
    assert "4th Annual Oktoberfest at The Red Barn Farm" not in titles


def test_local_events_with_a_city_but_no_coordinates_are_kept():
    ev = {e.title: e for e in _parse()}["St. Francis Festival"]
    assert ev.latitude is None and "Cherry Hill Township" in ev.venue_address


def test_no_radius_keeps_everything_with_a_start():
    assert len(parse_region(FIXTURE.read_text(), "patch")) == 16


def test_event_fields():
    by_title = {e.title: e for e in _parse()}
    ev = by_title["St. Francis Festival"]
    assert ev.start_time.isoformat() == "2026-10-10T13:00:00+00:00"
    assert ev.url.startswith("https://patch.com/new-jersey/cherryhill/calendar/event/20261010/")
    assert ev.is_free is True and ev.default_categories == ["patch"]
    assert {e.title: e for e in _parse()}["One Night With The Boobie Docs and Friends"].latitude
    paid = by_title["One Night With The Boobie Docs and Friends"]
    assert paid.is_free is None  # "paid" is a listing tier, not a price


def test_a_page_that_lost_its_calendar_raises():
    with pytest.raises(ValueError):
        region_events("<html><body>redesigned</body></html>")
    with pytest.raises(ValueError):
        region_events('<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>')


def test_prune_knows_patch_sources():
    assert "patch_sources" in SOURCE_KEYS
    pipeline = (Path(__file__).parent.parent / "local_events" / "pipeline.py").read_text()
    assert set(re.findall(r'params\.get\("(\w+_sources)"\)', pipeline)) <= set(SOURCE_KEYS)


def test_scraper_mode_goes_through_the_residential_first_chain(monkeypatch):
    import asyncio

    from local_events.sources import patch

    calls = []

    async def fake(url, **kw):
        calls.append((url, kw))
        return FIXTURE.read_text(), url

    monkeypatch.setattr(patch, "fetch_rendered_html", fake)
    monkeypatch.setattr(patch, "_PAUSE_SECONDS", 0)
    src = patch.PatchSource("patch", ["cherryhill", "haddon"], fetch_via="scraper")
    events = asyncio.run(src.fetch())
    assert len(events) == 16 and not src.partial_failures
    assert [c[0] for c in calls] == [
        "https://patch.com/new-jersey/cherryhill/calendar",
        "https://patch.com/new-jersey/haddon/calendar",
    ]
    assert all(c[1]["prefer_residential"] is True for c in calls)
    with pytest.raises(ValueError):
        patch.PatchSource("patch", ["x"], fetch_via="carrier-pigeon")
