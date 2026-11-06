"""Gives events a position, so /local can filter by distance.

A few feeds publish coordinates (Evvnt, Patch, Tribe, JSON-LD); most give an
address, some only a venue name, some nothing. Run after each refresh, this
fills latitude/longitude on the upcoming events that lack them, trying in
order:

1. the event's `venue_address`;
2. its `venue_name`, searched only inside the region (a name alone matches
   places all over the country);
3. the source's `location` param - an address or town an admin sets on a
   feed whose events all happen in one place it never states
   ("Evesham Township, NJ"), the same way `venue_address` is set;
4. where most of that source's other events are, when one spot holds the
   majority (a library whose feed omits the address on a few rows, or gives
   "Conference Center, Lower Level" as one).

An event none of these can place keeps null coordinates, and the API shows
it at every radius rather than hiding it: unknown is not "far away".

A place more than MAX_MILES from Cherry Hill counts as no answer, since
/local covers 50 miles: it is the geocoder's guess at a same-named street
elsewhere ("Main Street, Medford" came back in Massachusetts, "247 Oakland
Ave" in Iowa, a venue called "US" in the middle of the country), and it hid
the event at every radius. An event already put that far is placed again.

Every answer, including "no match", is cached in geocoded_places, so a run
only asks about venues it hasn't seen. Lookups are capped per run and
paced; a backlog (the first run after this
shipped, a big new feed) clears over the next runs.
"""
from __future__ import annotations

import asyncio
import logging
import math
from collections import Counter, defaultdict
from datetime import UTC, datetime, timedelta

import httpx
from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import GeocodedPlace, LocalEvent, ScheduledJob
from services.geocoding import geocode, geocode_name

from .prune import KIND, SOURCE_KEYS

logger = logging.getLogger(__name__)

# Cherry Hill, NJ: the middle of the box venue-name searches are kept to.
REGION_CENTER = (39.9268, -75.0246)
MAX_MILES = 100
# Degrees that stay inside MAX_MILES in every direction from REGION_CENTER,
# so the query can pass over what is plainly near without measuring it.
_NEAR_LAT = 1.0
_NEAR_LNG = 1.3
MAX_LOOKUPS = 250
PAUSE_SECONDS = 1.0
RETRY_MISS_AFTER = timedelta(days=30)
# Consecutive geocoder errors before the run gives up on lookups: a service
# that is down shouldn't cost the refresh job a 5s timeout per venue.
MAX_ERRORS = 5
_TIMEOUT = 5.0


def _key(kind: str, text: str) -> str:
    return f"{kind}:{' '.join(text.split()).lower()[:300]}"


def far(lat: float, lng: float) -> bool:
    """More than MAX_MILES from REGION_CENTER, as the crow flies."""
    lat0, lng0 = map(math.radians, REGION_CENTER)
    lat1, lng1 = math.radians(lat), math.radians(lng)
    a = math.sin((lat1 - lat0) / 2) ** 2 + math.cos(lat0) * math.cos(lat1) * math.sin((lng1 - lng0) / 2) ** 2
    return 2 * 3958.8 * math.asin(math.sqrt(a)) > MAX_MILES


def _near(coords: tuple[float, float] | None) -> tuple[float, float] | None:
    return coords if coords and not far(*coords) else None


def source_locations(params_list: list[dict | None]) -> dict[str, str]:
    """source name -> its `location` param, across every job's params."""
    out: dict[str, str] = {}
    for params in params_list:
        for key in SOURCE_KEYS:
            for entry in (params or {}).get(key) or []:
                if isinstance(entry, dict) and entry.get("name") and isinstance(entry.get("location"), str) and entry["location"].strip():
                    out[str(entry["name"])] = entry["location"].strip()
    return out


def _candidates(event: LocalEvent, hints: dict[str, str]) -> list[tuple[str, str]]:
    out = []
    if (event.venue_address or "").strip():
        out.append(("address", event.venue_address))
    if (event.venue_name or "").strip():
        out.append(("name", event.venue_name))
    if event.source in hints:
        out.append(("address", hints[event.source]))
    return out


async def _lookup(client: httpx.AsyncClient, kind: str, text: str) -> tuple[float, float] | None:
    if kind == "name":
        return await geocode_name(client, text, REGION_CENTER)
    return await geocode(client, " ".join(text.split()))


async def locate_events(db: AsyncSession) -> dict:
    """Fills coordinates on upcoming events without them, or with a far-off
    guess. Commits."""
    now = datetime.now(UTC)
    lat0, lng0 = REGION_CENTER
    events = [
        event
        for event in (
            await db.execute(
                select(LocalEvent).where(
                    or_(
                        LocalEvent.latitude.is_(None),
                        LocalEvent.longitude.is_(None),
                        func.abs(LocalEvent.latitude - lat0) > _NEAR_LAT,
                        func.abs(LocalEvent.longitude - lng0) > _NEAR_LNG,
                    ),
                    func.coalesce(LocalEvent.end_time, LocalEvent.start_time) >= now - timedelta(days=1),
                )
            )
        ).scalars()
        if event.latitude is None or event.longitude is None or far(event.latitude, event.longitude)
    ]
    if not events:
        return {"located": 0, "lookups": 0, "unplaced": 0}
    for event in events:
        event.latitude = event.longitude = None

    jobs = (await db.execute(select(ScheduledJob.params).where(ScheduledJob.kind == KIND))).scalars().all()
    hints = source_locations(jobs)
    plans = [(event, _candidates(event, hints)) for event in events]

    wanted = {_key(kind, text) for _, plan in plans for kind, text in plan}
    known: dict[str, tuple[float, float] | None] = {}
    for start in range(0, len(wanted), 500):
        chunk = list(wanted)[start : start + 500]
        for place in (await db.execute(select(GeocodedPlace).where(GeocodedPlace.query.in_(chunk)))).scalars():
            if place.latitude is not None and place.longitude is not None:
                known[place.query] = _near((place.latitude, place.longitude))
            elif place.looked_up_at > now - RETRY_MISS_AFTER:
                known[place.query] = None

    lookups = errors = located = 0
    waiting: set[str] = set()
    async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
        for event, plan in plans:
            for kind, text in plan:
                key = _key(kind, text)
                if key not in known:
                    if lookups >= MAX_LOOKUPS or errors >= MAX_ERRORS:
                        # Not asked yet. Stop here rather than fall through to
                        # a coarser guess the next run would have to undo.
                        waiting.add(event.id)
                        break
                    if lookups:
                        await asyncio.sleep(PAUSE_SECONDS)
                    lookups += 1
                    try:
                        coords = await _lookup(client, kind, text)
                    except Exception as exc:  # noqa: BLE001 - a geocoder outage must not fail the refresh
                        errors += 1
                        logger.warning("local_event_geocode_failed", extra={"query": key, "error": str(exc)})
                        waiting.add(event.id)
                        break
                    errors = 0
                    # The cache keeps what the geocoder said; a far answer is
                    # only set aside here.
                    known[key] = _near(coords)
                    await db.merge(
                        GeocodedPlace(query=key, latitude=coords[0] if coords else None, longitude=coords[1] if coords else None, looked_up_at=now)
                    )
                if known[key]:
                    event.latitude, event.longitude = known[key]
                    located += 1
                    break
    await db.flush()

    # 4: nothing above placed it (and nothing is still waiting to be asked),
    # but its source nearly always uses one place.
    bare = [event for event in events if event.latitude is None and event.id not in waiting]
    if bare:
        spots: dict[str, Counter] = defaultdict(Counter)
        rows = await db.execute(
            select(LocalEvent.source, LocalEvent.latitude, LocalEvent.longitude, func.count())
            .where(LocalEvent.source.in_({e.source for e in bare}), LocalEvent.latitude.is_not(None), LocalEvent.longitude.is_not(None))
            .group_by(LocalEvent.source, LocalEvent.latitude, LocalEvent.longitude)
        )
        for source, lat, lng, n in rows:
            if not far(lat, lng):
                spots[source][(lat, lng)] += n
        for event in bare:
            if not spots[event.source]:
                continue
            spot, n = spots[event.source].most_common(1)[0]
            if n * 2 > sum(spots[event.source].values()):
                event.latitude, event.longitude = spot
                located += 1

    await db.commit()
    summary = {"located": located, "lookups": lookups, "unplaced": len(events) - located - len(waiting)}
    if waiting:
        summary["waiting"] = len(waiting)
    logger.info("local_events_located", extra=summary)
    return summary
