"""The Today page's day-off picks: GET /local-events/day-off and the
ranking behind it (services/local_event_picks.py)."""
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import LocalEvent
from services import local_event_picks

pytestmark = pytest.mark.anyio

_ET = ZoneInfo("America/New_York")
CHERRY_HILL = {"near_lat": 39.93, "near_lng": -75.02, "radius_miles": 15}
HADDONFIELD = (39.8915, -75.0377)  # ~3 miles
MOORESTOWN = (39.9688, -74.9488)  # ~5 miles
LITITZ = (40.1573, -76.3069)  # ~70 miles
# Years out, so no real feed has anything on it in the shared local DB.
DAY = date(2035, 3, 14)


def _at(hour: int, minute: int = 0) -> datetime:
    return datetime(DAY.year, DAY.month, DAY.day, hour, minute, tzinfo=_ET)


async def test_day_off_picks_daytime_kids_events_nearest_first_without_paid_classes():
    src = f"dayoff_{uuid.uuid4().hex[:8]}"

    def event(title, categories, start, where=HADDONFIELD, **kw):
        lat, lng = where if where else (None, None)
        return LocalEvent(source=src, source_event_id=uuid.uuid4().hex, title=title, categories=categories, start_time=start, latitude=lat, longitude=lng, **kw)

    async with database.SessionLocal() as db:
        db.add_all(
            [
                event("Storytime", ["kids", "family"], _at(10)),
                # The same idea at a farther branch is one pick, the nearer.
                event("Storytime", ["kids"], _at(10, 30), MOORESTOWN),
                event("Family Concert", ["family"], _at(13), MOORESTOWN),
                event("Kids Swim Lessons", ["kids"], _at(9), price_min=40, price_max=40),
                event("Free Kids Art Workshop", ["kids"], _at(11), MOORESTOWN, is_free=True),
                event("Kids Glow Skate Night", ["kids"], _at(18)),
                event("Club Show", ["family", "music"], _at(20)),
                event("Toddler Time", ["kids", "family"], _at(10)),
                event("Teen Gaming", ["teen"], _at(14)),
                event("Unplaced Kids Fair", ["kids"], _at(12), None),
                event("Faraway Kids Fair", ["kids"], _at(12), LITITZ),
                event("Book Sale", ["library"], _at(10)),
                event("The Day Before", ["kids"], _at(10) - timedelta(days=1)),
            ]
        )
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        kids = (await client.get("/local-events/day-off", params={"day": DAY.isoformat(), **CHERRY_HILL})).json()
        assert [e["title"] for e in kids["items"]] == ["Storytime", "Free Kids Art Workshop", "Family Concert"]
        assert 2 < kids["items"][0]["miles"] < 4
        # Storytime x2, the concert, the free workshop, the evening skate - not
        # the late show, the toddlers' hour, the paid lessons or anything unplaced.
        assert kids["total"] == 5

        teens = (await client.get("/local-events/day-off", params={"day": DAY.isoformat(), "audience": "teens", **CHERRY_HILL})).json()
        assert [e["title"] for e in teens["items"]] == ["Teen Gaming", "Storytime", "Family Concert"]

        assert (await client.get("/local-events/day-off", params={"day": DAY.isoformat()})).status_code == 422
        assert (await client.get("/local-events/day-off", params={"day": DAY.isoformat(), "audience": "adults", **CHERRY_HILL})).status_code == 422


def test_todays_picks_leave_out_what_is_already_over():
    def row(title, start, end=None, all_day=False):
        return SimpleNamespace(title=title, categories=["kids"], description=None, is_free=None, price_max=None, start_time=start, end_time=end, all_day=all_day, miles=1.0)

    noon = _at(12)
    rows = [
        row("Morning Storytime", _at(10), _at(11)),
        row("Started, no end time", _at(10)),
        row("Just started", _at(11, 30)),
        row("Still running", _at(9), _at(15)),
        row("Museum Week", _at(0), all_day=True),
    ]
    picks, total = local_event_picks.day_off(rows, "kids", still_on_at=noon)
    assert total == 3
    assert {e.title for e in picks} == {"Just started", "Still running", "Museum Week"}
    # Another day's card keeps them all.
    assert local_event_picks.day_off(rows, "kids")[1] == 5
