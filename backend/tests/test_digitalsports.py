"""services/digitalsports.py against a real weekly page (Wood-Ridge, week of
2026-10-19, saved from call-school-ajax.php?filter=bydate)."""
import uuid
from datetime import UTC, date, datetime
from pathlib import Path

import httpx
import pytest
from sqlalchemy import select

import database
from models import District, School, SchoolContentItem
from scheduler.jobs import athletics_calendar_scan
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


@pytest.mark.anyio
async def test_a_site_shared_by_a_high_school_and_middle_school_is_split_by_team(monkeypatch):
    """Robbinsville's one site lists both schools, middle-school teams by name.
    A site with no sibling on it keeps every team, whatever they are called."""
    start = datetime(2026, 10, 14, 20, 0, tzinfo=UTC)

    def game(uid, team):
        return {"external_uid": uid, "kind": "game", "team": team, "title": f"{team} vs X", "description": None, "start_date": start, "end_date": None, "is_all_day": False}

    async def fake_fetch(host, window_start, window_end):
        return [game("1", "Soccer - Boys Varsity"), game("2", "Soccer - Boys Middle School")]

    monkeypatch.setattr(athletics_calendar_scan.digitalsports, "fetch_events", fake_fetch)
    tag = uuid.uuid4().hex[:8]
    url = f"https://shared{tag}.digitalsports.com/pages/schedule/schedule.php"

    async with database.SessionLocal() as db:
        district = District(name=f"DS District {tag}")
        db.add(district)
        await db.flush()
        high = School(name=f"DS High {tag}", slug=f"ds-high-{tag}", school_type="high", district_id=district.id, athletics_url=url)
        middle = School(name=f"DS Middle {tag}", slug=f"ds-middle-{tag}", school_type="middle", district_id=district.id, athletics_url=url)
        alone = School(name=f"DS Alone {tag}", slug=f"ds-alone-{tag}", school_type="high", athletics_url=f"https://alone{tag}.digitalsports.com/")
        db.add_all([high, middle, alone])
        await db.commit()

        async def teams(school):
            await athletics_calendar_scan.run(db, {"school_id": school.id})
            await db.flush()
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
            return {r.title for r in rows}

        assert await teams(high) == {"Soccer - Boys Varsity vs X"}
        assert await teams(middle) == {"Soccer - Boys Middle School vs X"}
        assert await teams(alone) == {"Soccer - Boys Varsity vs X", "Soccer - Boys Middle School vs X"}
