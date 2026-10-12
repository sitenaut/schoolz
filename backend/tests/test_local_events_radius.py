"""Distance on /local: the radius filter, the place lookup, and the step
that gives events coordinates (local_events/locate.py)."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import datetime, timedelta, timezone

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from local_events import locate
from local_events.sources.base import RawEvent, Source
from main import app
from models import GeocodedPlace, LocalEvent, ScheduledJob
from routers import local_events as local_events_router
from scheduler.jobs import local_events_refresh
from services.geocoding import Place

pytestmark = pytest.mark.anyio

CHERRY_HILL = {"near_lat": 39.93, "near_lng": -75.02}
HADDONFIELD = (39.8915, -75.0377)  # ~3 miles from Cherry Hill
LITITZ = (40.1573, -76.3069)  # ~70 miles


def _soon(days: int = 3) -> datetime:
    return datetime.now(timezone.utc) + timedelta(days=days)


async def test_radius_keeps_near_and_unplaced_events_and_reports_miles():
    src = f"radius_{uuid.uuid4().hex[:8]}"
    async with database.SessionLocal() as db:
        db.add_all(
            [
                LocalEvent(source=src, source_event_id="near", title="Near", start_time=_soon(), latitude=HADDONFIELD[0], longitude=HADDONFIELD[1], categories=["music"]),
                LocalEvent(source=src, source_event_id="far", title="Far", start_time=_soon(), latitude=LITITZ[0], longitude=LITITZ[1], categories=["arts"]),
                LocalEvent(source=src, source_event_id="unknown", title="Unknown", start_time=_soon(), categories=["music"]),
            ]
        )
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        everything = (await client.get("/local-events", params={"source": src})).json()
        assert everything["total"] == 3 and all(e["miles"] is None for e in everything["items"])

        measured = (await client.get("/local-events", params={"source": src, **CHERRY_HILL})).json()
        miles = {e["title"]: e["miles"] for e in measured["items"]}
        assert measured["total"] == 3 and miles["Unknown"] is None
        assert 2 < miles["Near"] < 4 and 65 < miles["Far"] < 75

        within = (await client.get("/local-events", params={"source": src, **CHERRY_HILL, "radius_miles": 15})).json()
        # An event we couldn't place is shown, not treated as far away.
        assert within["total"] == 2 and {e["title"] for e in within["items"]} == {"Near", "Unknown"}

        start = (_soon(-1)).isoformat()
        facets = (await client.get("/local-events/facets", params={"start": start, **CHERRY_HILL, "radius_miles": 15})).json()
        assert {"value": src, "count": 2} in facets["sources"]

        assert (await client.get("/local-events", params={"near_lat": 39.9})).status_code == 422
        assert (await client.get("/local-events", params={"radius_miles": 10})).status_code == 422


async def test_place_lookup(monkeypatch):
    async def fake_find_place(_client, query):
        return Place(39.8817, -74.971, "Cherry Hill Township 08003") if query == "08003" else None

    monkeypatch.setattr(local_events_router, "find_place", fake_find_place)
    monkeypatch.setattr(local_events_router, "_PLACE_MAX_PER_WINDOW", 2)
    local_events_router._place_requests_by_ip.clear()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        found = await client.post("/local-events/place", json={"q": "08003"})
        assert found.status_code == 200 and found.json() == {"label": "Cherry Hill Township 08003", "latitude": 39.8817, "longitude": -74.971}
        assert (await client.post("/local-events/place", json={"q": "nowhere at all"})).status_code == 404
        assert (await client.post("/local-events/place", json={"q": "08003"})).status_code == 429


async def test_locate_events_tries_address_then_name_then_source_location(monkeypatch):
    run = uuid.uuid4().hex[:8]
    hinted, library = f"township_{run}", f"library_{run}"
    asked: list[tuple[str, str]] = []
    answers = {
        ("address", f"60 N Haddon Ave {run}"): HADDONFIELD,
        ("name", f"Shirt Factory {run}"): LITITZ,
        ("address", f"Marlton {run}"): (39.8912, -74.9218),
    }

    async def fake_lookup(_client, kind, text):
        asked.append((kind, text))
        return answers.get((kind, text))

    monkeypatch.setattr(locate, "_lookup", fake_lookup)
    monkeypatch.setattr(locate, "MAX_LOOKUPS", 50)
    monkeypatch.setattr(locate, "PAUSE_SECONDS", 0)

    def event(source, key, **kw):
        return LocalEvent(source=source, source_event_id=key, title=f"{key} {run}", **{"start_time": _soon(), **kw})

    async with database.SessionLocal() as db:
        db.add(ScheduledJob(kind="local_events.refresh", name=f"radius {run}", cron_expr="0 5 * * *", params={"json_sources": [{"name": hinted, "url": "https://example.com", "location": f"Marlton {run}"}]}))
        db.add_all(
            [
                event(f"a_{run}", "address", venue_name="Library", venue_address=f"60 N Haddon Ave {run}"),
                event(f"a_{run}", "name", venue_name=f"Shirt Factory {run}"),
                event(f"a_{run}", "garbage", venue_address=f"19:00 {run}"),
                event(hinted, "hinted"),
                # A feed that omits the venue on one row: it goes where the rest are.
                event(library, "bare"),
                event(library, "placed1", latitude=39.9, longitude=-75.0),
                event(library, "placed2", latitude=39.9, longitude=-75.0),
                event(f"a_{run}", "past", venue_address=f"old {run}", start_time=_soon(-30)),
            ]
        )
        await db.commit()
        first = await locate.locate_events(db)
        rows = (await db.execute(select(LocalEvent).where(LocalEvent.title.like(f"% {run}")))).scalars().all()
        where = {r.source_event_id: (r.latitude, r.longitude) for r in rows}
        missed = await db.get(GeocodedPlace, f"address:19:00 {run}")
        asked_first = list(asked)
        again = await locate.locate_events(db)

    assert where["address"] == HADDONFIELD and where["name"] == LITITZ
    assert where["hinted"] == (39.8912, -74.9218) and where["bare"] == (39.9, -75.0)
    assert where["garbage"] == (None, None) and where["past"] == (None, None)
    assert ("address", f"old {run}") not in asked_first
    assert missed is not None and missed.latitude is None
    assert first["located"] >= 4 and first["lookups"] >= 4
    # Every answer is cached, the miss included: nothing is asked twice.
    assert asked == asked_first and again["lookups"] == 0


async def test_refresh_keeps_a_located_events_position(monkeypatch):
    run = uuid.uuid4().hex[:8]

    class Feed(Source):
        name = f"feed_{run}"

        async def fetch(self):
            return [RawEvent(source=self.name, source_event_id="1", title=f"Story Time {run}", start_time=_soon(), venue_address=f"1 Main St {run}")]

    async def fake_lookup(_client, _kind, _text):
        return HADDONFIELD

    monkeypatch.setattr(locate, "_lookup", fake_lookup)
    monkeypatch.setattr(locate, "MAX_LOOKUPS", 50)
    monkeypatch.setattr(locate, "PAUSE_SECONDS", 0)
    monkeypatch.setattr("local_events.pipeline._build_sources", lambda _params: [Feed()])
    async with database.SessionLocal() as db:
        await local_events_refresh.run(db, {})
        # The second run has no lookup budget, like a run where the geocoder is down.
        monkeypatch.setattr(locate, "MAX_LOOKUPS", 0)
        await db.execute(GeocodedPlace.__table__.delete().where(GeocodedPlace.query == f"address:1 main st {run}"))
        await local_events_refresh.run(db, {})
        row = (await db.execute(select(LocalEvent).where(LocalEvent.source == f"feed_{run}"))).scalar_one()
    assert (row.latitude, row.longitude) == HADDONFIELD
