"""services/digitalsports.py against a real weekly page (Wood-Ridge, week of
2026-10-19, saved from call-school-ajax.php?filter=bydate)."""
from datetime import date
from pathlib import Path

import httpx
import pytest

from services import digitalsports
from services.digitalsports import fetch_events, host_from_athletics_url, parse_week

_WEEK = (Path(__file__).parent / "fixtures" / "digitalsports_week_2026_10_19.html").read_text()


def test_host_from_athletics_url():
    assert host_from_athletics_url("https://wood-ridgeathletics.digitalsports.com/pages/schedule/schedule.php") == "wood-ridgeathletics"
    assert host_from_athletics_url("https://wood-ridgeathletics.digitalsports.com") == "wood-ridgeathletics"
    assert host_from_athletics_url("https://www.digitalsports.com/") is None
    assert host_from_athletics_url("https://www.arbiterlive.com/m/team/4714") is None
    assert host_from_athletics_url(None) is None


def test_parse_week_reads_home_and_away_games():
    by_uid = {e["external_uid"]: e for e in parse_week(_WEEK)}
    assert len(by_uid) == 16

    away = by_uid["ds:7483894"]
    assert away["title"] == "Soccer - Boys Junior Varsity @ Hasbrouck Heights High School"
    assert away["description"] == "Hasbrouck Heights - Hitchcock Field (Soccer Field)"
    assert (away["start_date"].date(), away["start_date"].hour, away["start_date"].minute) == (date(2026, 10, 19), 16, 0)
    assert away["is_all_day"] is False

    home = by_uid["ds:7440010"]
    assert home["title"] == "Soccer - Boys Varsity vs Hasbrouck Heights High School"
    # The reschedule note is kept, the bare "Game" label is not.
    assert home["description"] == "Wood-Ridge Athletic Complex 30 Kennedy Lane- Soccer - (Rescheduled from 10-19-26)"
    assert home["kind"] == "game"


def test_parse_week_opponent_with_a_tooltip_link_and_school_events():
    by_uid = {e["external_uid"]: e for e in parse_week(_WEEK)}
    # "Leonia/Palisades" is itself a link; the venue is the details link.
    assert by_uid["ds:7499995"]["title"] == "Soccer - Girls Varsity vs Leonia/Palisades"
    assert by_uid["ds:7499995"]["description"] == "Wood-Ridge Athletic Complex 30 Kennedy Lane- Soccer"
    # A team-less school event is named from its details cell; a TBD venue is dropped.
    event = by_uid["ds:7573706"]
    assert (event["kind"], event["title"], event["description"]) == ("event", "National Junior Honor Society Induction", None)


def test_parse_week_drops_practices():
    html = _WEEK.replace("Soccer: Boys Varsity Game", "Soccer: Boys Varsity Practice")
    assert "ds:7440010" not in {e["external_uid"] for e in parse_week(html)}


def test_week_starts_tile_the_range_from_mondays():
    weeks = digitalsports._week_starts(date(2026, 10, 14), date(2026, 10, 30))
    assert weeks == [date(2026, 10, 12), date(2026, 10, 19), date(2026, 10, 26)]


@pytest.mark.anyio
async def test_fetch_events_pages_week_by_week_and_clips_to_the_window(monkeypatch):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append(request.url.params["date"])
        return httpx.Response(200, text=_WEEK if request.url.params["date"] == "2026-10-19" else "")

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    events = await fetch_events("wood-ridgeathletics", date(2026, 10, 14), date(2026, 10, 21))
    assert asked == ["2026-10-12", "2026-10-19"]
    # Only events dated within [start, end] survive (Oct 19-21 of the week's 16).
    assert {e["start_date"].date() for e in events} == {date(2026, 10, 19), date(2026, 10, 20), date(2026, 10, 21)}


@pytest.mark.anyio
async def test_fetch_events_raises_when_every_week_fails(monkeypatch):
    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(lambda r: httpx.Response(503)), **kw))
    with pytest.raises(httpx.HTTPError):
        await fetch_events("wood-ridgeathletics", date(2026, 10, 14), date(2026, 10, 21))
