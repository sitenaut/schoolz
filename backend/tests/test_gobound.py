"""services/gobound.py against a feed in the shape of a real GoBound calendar
subscription (Kingsway Regional's, trimmed and with made-up ids)."""
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from pathlib import Path

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import httpx
import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import District, ScheduledJob, School, SchoolContentItem, User
from scheduler.jobs import athletics_calendar_scan
from services import gobound

_FEED = (Path(__file__).parent / "fixtures" / "gobound_feed.ics").read_bytes()
_URL = "https://gobound.com/nj/schools/kingswayregionalhs/calendar/ical/2ff399a9860f47a"


def _parsed(start=date(2026, 10, 1), end=date(2027, 3, 31)) -> dict[str, dict]:
    return {e["external_uid"]: e for e in gobound.parse_feed(_FEED, start, end)}


def test_feed_urls_are_recognised_and_linked_to_the_school_page():
    for url in (_URL, _URL.replace("https://", "https://www."), _URL.replace("https://", "webcal://"), _URL + "/", _URL + "?x=1"):
        assert gobound.feed_url(url) == _URL
        assert gobound.school_key(url) == ("nj", "schools", "kingswayregionalhs", ())
        assert gobound.page_url(url) == "https://gobound.com/nj/schools/kingswayregionalhs"
        assert gobound.team_names(url) == ()
    # Another token for the same school is the same school.
    assert gobound.school_key(_URL.replace("2ff399a9860f47a", "0123456789abcde")) == ("nj", "schools", "kingswayregionalhs", ())
    # The school's own page has no calendar file to read, and other vendors aren't GoBound.
    for other in ("https://gobound.com/nj/schools/kingswayregionalhs", "https://www.arbiterlive.com/m/team/11862", "", None):
        assert gobound.feed_url(other) is None
        assert gobound.page_url(other) is None


def test_a_conference_link_names_its_teams_after_the_hash():
    feed = "https://gobound.com/nj/conferences/tricountyconference/calendar/ical/696b69dead46463"
    for url in (f"{feed}#Deptford|Deptford High School", f"{feed}#Deptford%7CDeptford%20High%20School", f"{feed}#Deptford | Deptford  High School|"):
        assert gobound.feed_url(url) == feed  # the names are never sent
        assert gobound.team_names(url) == ("Deptford", "Deptford High School")
        assert gobound.school_key(url) == ("nj", "conferences", "tricountyconference", ("deptford", "deptford high school"))
        assert gobound.page_url(url) == "https://gobound.com/nj/conferences/tricountyconference"
    # Another school's games in the same conference feed are another key.
    assert gobound.school_key(f"{feed}#Highland Regional") != gobound.school_key(f"{feed}#Deptford")


def test_games_and_every_other_event_are_kept():
    by_uid = _parsed()
    assert len(by_uid) == 12
    # Practices, rehearsals and room bookings are /direct/noncomps/: kept, as events.
    practice, rehearsal = by_uid["gb:h20261020000000012aaaaaaaaaaaaa"], by_uid["gb:h20261020000000013aaaaaaaaaaaaa"]
    assert (practice["kind"], practice["title"]) == ("event", "Girls Basketball Practice")
    assert (rehearsal["kind"], rehearsal["title"]) == ("event", "Indoor Percussion Rehearsal")
    assert rehearsal["description"].startswith("Kingsway Regional Middle School")
    assert sum(1 for e in by_uid.values() if e["kind"] == "game") == 10


def test_a_game_reads_title_venue_team_and_times():
    game = _parsed()["gb:h20261020000000001aaaaaaaaaaaaa"]
    assert game["title"] == "Girls Field Hockey: Jackson Township vs Kingsway Regional (Varsity)"
    assert game["description"] == 'Kingsway Regional High School Anthony "Tony" Barchuk Stadium'
    assert game["team"] == "Girls Field Hockey - Varsity"
    assert game["start_date"] == datetime(2026, 11, 2, 20, 0, tzinfo=UTC)
    assert game["end_date"] == datetime(2026, 11, 2, 22, 0, tzinfo=UTC)
    assert game["is_all_day"] is False


def test_a_game_with_no_time_yet_is_all_day_on_its_date():
    game = _parsed()["gb:h20261020000000006aaaaaaaaaaaaa"]
    assert game["is_all_day"] is True
    assert game["start_date"].isoformat() == "2026-11-04T00:00:00-05:00"
    assert game["end_date"] is None
    assert game["title"].endswith("(Time TBA)")


def test_called_off_games_say_so_once():
    by_uid = _parsed()
    assert by_uid["gb:h20261020000000007aaaaaaaaaaaaa"]["title"] == "CANCELLED - Girls Basketball: Kingsway Regional vs Highland Regional (Junior Varsity)"
    assert by_uid["gb:h20261020000000008aaaaaaaaaaaaa"]["title"] == "POSTPONED - Girls Wrestling: Kingsway Regional vs Manchester Township (Varsity)"
    # A cancelled game whose title doesn't say it gets the prefix.
    assert by_uid["gb:h20261020000000009aaaaaaaaaaaaa"]["title"] == "CANCELLED - Softball: Kingsway Regional vs Williamstown (Freshman)"


def test_an_unknown_venue_is_left_out():
    assert _parsed()["gb:h20261020000000010aaaaaaaaaaaaa"]["description"] is None


def test_games_are_clipped_to_the_window():
    assert "gb:h20261020000000011aaaaaaaaaaaaa" not in _parsed()  # last season
    assert "gb:h20261020000000010aaaaaaaaaaaaa" in _parsed(end=date(2027, 2, 27))
    assert "gb:h20261020000000010aaaaaaaaaaaaa" not in _parsed(end=date(2027, 2, 26))


def test_middle_school_teams_are_told_apart_by_level_and_activity():
    by_uid = _parsed()
    middle = {uid for uid, e in by_uid.items() if gobound.is_middle_school_team(e)}
    assert middle == {
        "gb:h20261020000000002aaaaaaaaaaaaa",  # 8th Grade
        "gb:h20261020000000003aaaaaaaaaaaaa",  # Cross Country (coed) (MS ONLY)
        "gb:h20261020000000004aaaaaaaaaaaaa",  # MS Red
    }
    # A varsity game against a middle school's name is still the high school's.
    assert not gobound.is_middle_school_team(by_uid["gb:h20261020000000005aaaaaaaaaaaaa"])
    for team in ("Baseball - Level 2", "Cheer - Fall JV Cheer", "Boys Hockey - JV", "Girls Bowling - Varsity"):
        assert not gobound.is_middle_school_team({"team": team})
    assert gobound.is_middle_school_team({"team": "Girls Volleyball - 7th Grade"})
    assert gobound.is_middle_school_team({"team": "Girls Field Hockey - MS Black"})


def test_other_events_belong_to_the_building_they_are_in():
    by_uid = _parsed()
    assert gobound.is_middle_school_item(by_uid["gb:h20261020000000013aaaaaaaaaaaaa"])  # the middle school's West Gym
    assert not gobound.is_middle_school_item(by_uid["gb:h20261020000000012aaaaaaaaaaaaa"])  # the high school's North Gym
    # A game still goes by its team, wherever it is played.
    assert gobound.is_middle_school_item(by_uid["gb:h20261020000000004aaaaaaaaaaaaa"])
    assert not gobound.is_middle_school_item(by_uid["gb:h20261020000000005aaaaaaaaaaaaa"])


def _conference_feed(*events: tuple[str, str, str]) -> bytes:
    """A conference calendar: (uid, summary, start) per game. Like the real
    Tri-County Conference feed it has no level field."""
    body = "".join(
        f"BEGIN:VEVENT\r\nUID:{uid}\r\nSUMMARY:{summary}\r\nDTSTART;TZID=America/New_York:{start}\r\nSTATUS:CONFIRMED\r\n"
        f"LOCATION:Somewhere Field\r\nURL:https://gobound.com/direct/comps/{uid}/show\r\nX-BND-ACTIVITYNAME:{summary.split(':')[0]}\r\nEND:VEVENT\r\n"
        for uid, summary, start in events
    )
    return f"BEGIN:VCALENDAR\r\nVERSION:2.0\r\nX-WR-CALNAME:Tri-County Conference Calendar\r\n{body}END:VCALENDAR\r\n".encode()


def test_a_conference_feed_keeps_only_the_named_teams_games():
    feed = _conference_feed(
        ("c1", "Boys Soccer: Deptford vs Woodstown (Varsity)", "20261110T150000"),
        ("c2", "Girls Basketball: Pitman vs Deptford High School (Junior Varsity)", "20261211T160000"),
        ("c3", "Girls Soccer: Clayton/Glassboro vs Penns Grove (Varsity)", "20261112T150000"),
        ("c4", "Wrestling: West Deptford vs Highland Regional (Varsity)", "20261212T100000"),  # not "Deptford"
        ("c5", "Swim Meet: Deptford Invitational (Varsity)", "20261213T100000"),  # no "vs": nobody's game
        ("c6", "CANCELLED - Boys Basketball: Deptford (Middle School) vs Overbrook (Middle School)", "20261214T160000"),
    )
    games = {e["external_uid"]: e for e in gobound.parse_feed(feed, date(2026, 10, 1), date(2027, 3, 31), ("Deptford", "Deptford High School"))}
    assert set(games) == {"gb:c1", "gb:c2", "gb:c6"}
    # The level comes from the title when the feed has no level field.
    assert games["gb:c1"]["team"] == "Boys Soccer - Varsity"
    assert gobound.is_middle_school_team(games["gb:c6"])
    assert set(e["external_uid"] for e in gobound.parse_feed(feed, date(2026, 10, 1), date(2027, 3, 31), ("Glassboro",))) == {"gb:c3"}


@pytest.mark.anyio
async def test_fetch_events_reads_the_https_feed_once(monkeypatch):
    asked = []

    def handler(request: httpx.Request) -> httpx.Response:
        asked.append((str(request.url), request.headers["user-agent"]))
        return httpx.Response(200, content=_FEED, headers={"content-type": "text/calendar; charset=utf-8"})

    real = httpx.AsyncClient
    monkeypatch.setattr(httpx, "AsyncClient", lambda **kw: real(transport=httpx.MockTransport(handler), **kw))
    events = await gobound.fetch_events(_URL.replace("https://", "webcal://www."), date(2026, 10, 1), date(2027, 3, 31))
    assert asked == [(_URL, "schoolz-athletics/1.0")]
    assert len(events) == 12
    # A conference link's team names stay on our side of the "#".
    asked.clear()
    await gobound.fetch_events(_URL + "#Kingsway Regional", date(2026, 10, 1), date(2027, 3, 31))
    assert asked == [(_URL, "schoolz-athletics/1.0")]


def _game(uid: str, team: str, when: datetime) -> dict:
    return {"external_uid": uid, "kind": "game", "team": team, "title": f"{team} vs X", "description": None, "start_date": when, "end_date": None, "is_all_day": False}


def _event(uid: str, title: str, where: str, when: datetime) -> dict:
    return {"external_uid": uid, "kind": "event", "team": "", "title": title, "description": where, "location": where, "start_date": when, "end_date": None, "is_all_day": False}


@pytest.mark.anyio
async def test_a_feed_shared_by_a_high_school_and_middle_school_is_split_by_team(monkeypatch):
    """Kingsway's high-school page carries the middle school's teams, and the
    rehearsals in its building. A school with no sibling on GoBound keeps all."""
    when = datetime.now(UTC) + timedelta(days=3)

    async def fake_fetch(url, window_start, window_end):
        return [
            _game("gb:1", "Girls Soccer - Varsity", when),
            _game("gb:2", "Girls Soccer - 8th Grade", when),
            _event("gb:3", "Musical Rehearsal", "Kingsway Regional High School Eitel Theater", when),
            _event("gb:4", "MS Musical Practice", "Kingsway Regional Middle School MS Cafeteria", when),
        ]

    monkeypatch.setattr(athletics_calendar_scan.gobound, "fetch_events", fake_fetch)
    tag = uuid.uuid4().hex[:8]
    url = f"https://gobound.com/nj/schools/shared{tag}/calendar/ical/abc123"

    async with database.SessionLocal() as db:
        district = District(name=f"GB District {tag}")
        db.add(district)
        await db.flush()
        high = School(name=f"GB High {tag}", slug=f"gb-high-{tag}", school_type="high", district_id=district.id, athletics_url=url)
        # A different token for the same school page is still that page's feed.
        middle = School(name=f"GB Middle {tag}", slug=f"gb-middle-{tag}", school_type="middle", district_id=district.id, athletics_url=url.replace("abc123", "def456"))
        alone = School(name=f"GB Alone {tag}", slug=f"gb-alone-{tag}", school_type="high", athletics_url=f"https://gobound.com/nj/schools/alone{tag}/calendar/ical/abc123")
        db.add_all([high, middle, alone])
        await db.commit()

        async def titles(school):
            await athletics_calendar_scan.run(db, {"school_id": school.id})
            await db.flush()
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
            assert {r.source for r in rows} == {"gobound"}
            return {r.title for r in rows}

        assert await titles(high) == {"Girls Soccer - Varsity vs X", "Musical Rehearsal"}
        assert await titles(middle) == {"Girls Soccer - 8th Grade vs X", "MS Musical Practice"}
        assert await titles(alone) == {"Girls Soccer - Varsity vs X", "Girls Soccer - 8th Grade vs X", "Musical Rehearsal", "MS Musical Practice"}


@pytest.mark.anyio
async def test_a_school_whose_gobound_calendar_is_its_events_calendar_shows_them(monkeypatch):
    """Williamstown's non-game events are its dances and class trips: shown
    like any school event once the school is switched on, and moved (same row)
    when the switch changes. Its games stay behind the sports toggle."""
    when = datetime.now(UTC) + timedelta(days=4)

    async def fake_fetch(url, window_start, window_end):
        return [_game("gb:g", "Football - Varsity", when), _event("gb:e", "Homecoming Dance", "Williamstown High School Gym", when)]

    monkeypatch.setattr(athletics_calendar_scan.gobound, "fetch_events", fake_fetch)
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"GB Events {tag}", slug=f"gb-events-{tag}", school_type="high", athletics_url=f"https://gobound.com/nj/schools/ev{tag}/calendar/ical/abc123")
        db.add(school)
        await db.commit()

        async def sources():
            await athletics_calendar_scan.run(db, {"school_id": school.id})
            await db.flush()
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
            return {r.external_uid: (r.source, r.id) for r in rows}

        hidden = await sources()
        assert {uid: src for uid, (src, _) in hidden.items()} == {"gb:g": "gobound", "gb:e": "gobound"}
        school.arbiter_events_calendar = True
        await db.commit()
        shown = await sources()
        assert {uid: src for uid, (src, _) in shown.items()} == {"gb:g": "gobound", "gb:e": "gobound_events"}
        assert shown["gb:e"][1] == hidden["gb:e"][1]


@pytest.mark.anyio
async def test_a_dropped_game_goes_and_the_old_sources_games_are_retired(monkeypatch):
    """A game gone from the feed (moved, deleted) is removed. A school that
    moved to GoBound loses its ArbiterLive games in the window, which the feed
    repeats; older ones, and other schools' games, stay."""
    now = datetime.now(UTC)
    listed = [_game("gb:keep", "Football - Varsity", now + timedelta(days=5)), _game("gb:drop", "Football - Junior Varsity", now + timedelta(days=6))]

    async def fake_fetch(url, window_start, window_end):
        return list(listed)

    monkeypatch.setattr(athletics_calendar_scan.gobound, "fetch_events", fake_fetch)
    tag = uuid.uuid4().hex[:8]

    async with database.SessionLocal() as db:
        school = School(name=f"GB Moved {tag}", slug=f"gb-moved-{tag}", school_type="high", athletics_url=f"https://gobound.com/nj/schools/moved{tag}/calendar/ical/abc123")
        other = School(name=f"GB Other {tag}", slug=f"gb-other-{tag}", school_type="high", athletics_url="https://www.arbiterlive.com/m/team/1")
        db.add_all([school, other])
        await db.flush()

        def arbiter_row(owner, uid, when):
            return SchoolContentItem(scope="school", school_id=owner.id, category="event", source="arbiter_athletics", external_uid=uid, title=f"Arbiter {uid}", start_date=when, is_all_day=False)

        db.add_all(
            [
                arbiter_row(school, "100", now + timedelta(days=5)),  # the same game, from Arbiter
                arbiter_row(school, "101", now - timedelta(days=90)),  # last season, outside the window
                arbiter_row(other, "102", now + timedelta(days=5)),
            ]
        )
        await db.commit()

        first = await athletics_calendar_scan.run(db, {"school_id": school.id})
        assert "2 new" in first and "1 from the school's previous source retired" in first
        listed.pop()  # the JV game is called off and taken down
        second = await athletics_calendar_scan.run(db, {"school_id": school.id})
        assert "1 removed" in second and "retired" not in second
        await db.flush()

        rows = (await db.execute(select(SchoolContentItem.external_uid, SchoolContentItem.source).where(SchoolContentItem.school_id.in_((school.id, other.id))))).all()
        assert sorted(rows) == [("101", "arbiter_athletics"), ("102", "arbiter_athletics"), ("gb:keep", "gobound")]


@pytest.mark.anyio
async def test_a_seeded_feed_gets_a_scan_and_parents_get_the_school_page():
    run_id = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"admin_{run_id}@example.com"
        reg = await client.post("/auth/register", json={"email": email, "username": f"admin_{run_id}", "password": "password123"})
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
        headers = {"authorization": f"Bearer {reg.json()['access_token']}"}
        slug, district = f"gb-seed-{run_id}", f"GB Seed {run_id}"
        school = {
            "slug": slug, "name": f"GB Seed High {run_id}", "short_name": None, "district_name": district, "school_type": "high",
            "absence_emails": [], "website_url": None, "athletics_url": _URL,
            **{k: None for k in ("address", "main_phone", "absence_method", "absence_phone", "absence_portal_name", "absence_portal_url",
                                 "absence_instructions", "start_time", "end_time", "early_dismissal_time", "delayed_opening_time",
                                 "logo_url", "bell_periods", "sacc")},
        }
        body = {"exported_at": "2026-01-01T00:00:00Z", "source": "test", "smore_newsletters": [], "schools": [school],
                "districts": [{"name": district, "website_url": "https://example.org", "food_services_menu_url": None, "ics_feeds": [],
                               **{k: None for k in ("marking_period_url", "preschool_locations_url", "preschool_team_url", "hs_rotation_url", "transportation_url")}}]}
        res = await client.post("/admin/config/import", json=body, headers=headers)
        assert res.status_code == 200, res.text

        out = (await client.get(f"/schools/{slug}")).json()
        assert out["athletics_url"] == _URL
        assert out["athletics_link"] == "https://gobound.com/nj/schools/kingswayregionalhs"

        async with database.SessionLocal() as db:
            job_id = (await db.execute(select(School.athletics_calendar_job_id).where(School.slug == slug))).scalar_one()
            job = await db.get(ScheduledJob, job_id)
        assert job is not None and job.kind == "athletics_calendar.scan"
