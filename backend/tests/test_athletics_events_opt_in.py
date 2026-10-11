import uuid
from datetime import datetime, timezone

import pytest
from sqlalchemy import select

import database
from models import School, SchoolContentItem
from scheduler.jobs import athletics_calendar_scan


def _feed():
    start = datetime(2026, 10, 14, 13, 0, tzinfo=timezone.utc)
    return [
        {"external_uid": "501", "kind": "game", "team": "Soccer - Boys Varsity", "title": "Soccer - Boys Varsity vs Pitman", "description": "Field", "start_date": start, "end_date": None, "is_all_day": False},
        {"external_uid": "event:9", "kind": "event", "team": "Field trip", "title": "FIELD TRIP: Book Club", "description": None, "start_date": start, "end_date": None, "is_all_day": False},
    ]


async def _sources(db, school_id):
    rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school_id))).scalars().all()
    return {r.title: r.source for r in rows}


@pytest.mark.anyio
async def test_arbiter_events_are_shown_only_for_a_school_switched_on(monkeypatch):
    """An Arbiter "event" is team business (open gyms, team dinners) at most
    schools, so it stays hidden with the games; Gateway publishes its school
    events there and is switched on."""

    async def fake_fetch(entity_id, start, end):
        return [dict(e) for e in _feed()]

    async def no_status(entity_id, start, end):
        return {}

    monkeypatch.setattr(athletics_calendar_scan, "fetch_events", fake_fetch)
    monkeypatch.setattr(athletics_calendar_scan, "fetch_statuses", no_status)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Arb School {tag}", slug=f"arb-{tag}", school_type="high", athletics_url="https://www.arbiterlive.com/School/Calendar/8327")
        db.add(school)
        await db.commit()

        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        assert set((await _sources(db, school.id)).values()) == {"arbiter_athletics"}

        # Switching the school on re-tags the event it already stored (no duplicate).
        school.arbiter_events_calendar = True
        await db.flush()
        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        assert await _sources(db, school.id) == {
            "Soccer - Boys Varsity vs Pitman": "arbiter_athletics",
            "FIELD TRIP: Book Club": "arbiter_events",
        }

        # And off again puts it back with the games.
        school.arbiter_events_calendar = False
        await db.flush()
        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        assert set((await _sources(db, school.id)).values()) == {"arbiter_athletics"}


@pytest.mark.anyio
async def test_cancelled_games_are_marked_in_the_title_and_restored_when_back_on(monkeypatch):
    state = {"statuses": {"501": "Canceled"}}

    async def fake_fetch(entity_id, start, end):
        return [dict(e) for e in _feed()]

    async def fake_statuses(entity_id, start, end):
        return dict(state["statuses"])

    monkeypatch.setattr(athletics_calendar_scan, "fetch_events", fake_fetch)
    monkeypatch.setattr(athletics_calendar_scan, "fetch_statuses", fake_statuses)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Arb Status {tag}", slug=f"arbs-{tag}", school_type="high", athletics_url="https://www.arbiterlive.com/School/Calendar/8327")
        db.add(school)
        await db.commit()

        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        titles = set(await _sources(db, school.id))
        assert "CANCELED - Soccer - Boys Varsity vs Pitman" in titles

        # The game is back on: the same row loses the mark (no second row).
        state["statuses"] = {}
        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        assert set(await _sources(db, school.id)) == {"Soccer - Boys Varsity vs Pitman", "FIELD TRIP: Book Club"}


@pytest.mark.anyio
async def test_a_districts_calendar_kept_on_one_schools_arbiter_account_is_district_scoped(monkeypatch):
    """Audubon runs one district calendar on its high school's Arbiter account.
    Its events are then the district's - every school shows them - while the
    games stay the high school's own."""
    from models import District

    async def fake_fetch(entity_id, start, end):
        return [dict(e) for e in _feed()]

    async def no_status(entity_id, start, end):
        return {}

    monkeypatch.setattr(athletics_calendar_scan, "fetch_events", fake_fetch)
    monkeypatch.setattr(athletics_calendar_scan, "fetch_statuses", no_status)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Arb District {tag}")
        db.add(district)
        await db.flush()
        school = School(
            name=f"Arb HS {tag}", slug=f"arbhs-{tag}", school_type="high", district_id=district.id,
            athletics_url="https://arbiterlive.com/School/Calendar/975", arbiter_events_calendar=True, arbiter_events_district_wide=True,
        )
        db.add(school)
        await db.commit()

        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        rows = {r.title: r for r in (await db.execute(select(SchoolContentItem).where(SchoolContentItem.source.in_(("arbiter_events", "arbiter_athletics")), (SchoolContentItem.school_id == school.id) | (SchoolContentItem.district_id == district.id)))).scalars().all()}
        trip, game = rows["FIELD TRIP: Book Club"], rows["Soccer - Boys Varsity vs Pitman"]
        assert (trip.scope, trip.district_id, trip.school_id, trip.source) == ("district", district.id, None, "arbiter_events")
        assert (game.scope, game.school_id, game.source) == ("school", school.id, "arbiter_athletics")

        # A re-scan updates the district-wide row in place, and turning the option off moves it back.
        await athletics_calendar_scan.run(db, {"school_id": school.id})
        school.arbiter_events_district_wide = False
        await db.flush()
        await athletics_calendar_scan.run(db, {"school_id": school.id})
        await db.flush()
        again = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.title == "FIELD TRIP: Book Club", (SchoolContentItem.school_id == school.id) | (SchoolContentItem.district_id == district.id)))).scalars().all()
        assert len(again) == 1 and (again[0].scope, again[0].school_id, again[0].district_id) == ("school", school.id, None)
