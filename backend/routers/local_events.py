"""Read API for the local events feed (/local). Public, no login required -
same access model as schools/districts/calendar: community data pulled from
third-party feeds is still worth bookmarking with no account."""

import os
import time
from collections import defaultdict, deque
from datetime import UTC, date, datetime, timedelta
from datetime import time as dtime
from urllib.parse import parse_qsl
from zoneinfo import ZoneInfo

import httpx
from fastapi import APIRouter, Depends, HTTPException, Path, Query, Request, Response
from pydantic import BaseModel, Field, TypeAdapter
from sqlalchemy import and_, case, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import database
from database import get_db
from models import LocalEvent, ResourceService
from services.client_ip import client_ip
from services.geocoding import find_place
from services.i18n import fold, folded
from services.response_cache import SingleFlightTTLCache

router = APIRouter(prefix="/local-events", tags=["local-events"])

# /local-events/place asks Census and Nominatim on the visitor's behalf, so
# it's limited per IP the way /chat is (in-memory, per machine): enough for
# someone retyping an address, not for using us as a free geocoder.
_PLACE_WINDOW_SECONDS = 600
_PLACE_MAX_PER_WINDOW = 20
_place_requests_by_ip: dict[str, deque[float]] = defaultdict(deque)


class LocalEventOut(BaseModel):
    id: str
    source: str
    title: str
    description: str | None
    start_time: datetime
    end_time: datetime | None
    all_day: bool
    venue_name: str | None
    venue_address: str | None
    url: str | None
    image_url: str | None
    price_min: float | None
    price_max: float | None
    is_free: bool | None
    categories: list[str]
    # Straight-line miles from the point asked about; null with no point, or
    # when we don't know where the event is.
    miles: float | None = None

    model_config = {"from_attributes": True}


class LocalEventListOut(BaseModel):
    items: list[LocalEventOut]
    total: int


class LocalEventRowOut(BaseModel):
    """One row of the /local list: only what a row shows. The page fetches the
    rest (description, address, image, link) by id when the event is opened -
    descriptions alone were over half the bytes of a month."""

    id: str
    source: str
    title: str
    start_time: datetime
    end_time: datetime | None
    all_day: bool
    venue_name: str | None
    price_min: float | None
    price_max: float | None
    is_free: bool | None
    categories: list[str]
    miles: float | None = None

    model_config = {"from_attributes": True}


class LocalEventRowsOut(BaseModel):
    items: list[LocalEventRowOut]
    total: int


class LocalEventDaysOut(BaseModel):
    # "YYYY-MM-DD" (Cherry Hill's date) -> events on that day, inside the range.
    days: dict[str, int]
    total: int


class FacetOut(BaseModel):
    value: str
    count: int


class LocalEventFacetsOut(BaseModel):
    categories: list[FacetOut]
    sources: list[FacetOut]


class PlaceIn(BaseModel):
    q: str = Field(min_length=2, max_length=200)


class PlaceOut(BaseModel):
    label: str
    latitude: float
    longitude: float


class Near:
    """`near_lat` + `near_lng` (+ `radius_miles`): the point distances are
    measured from. A radius keeps events within it *and* events we couldn't
    place - an unknown location is shown, never silently dropped."""

    def __init__(
        self,
        near_lat: float | None = Query(None, ge=-90, le=90),
        near_lng: float | None = Query(None, ge=-180, le=180),
        radius_miles: float | None = Query(None, gt=0, le=500),
    ):
        if (near_lat is None) != (near_lng is None):
            raise HTTPException(422, "near_lat and near_lng go together")
        if radius_miles is not None and near_lat is None:
            raise HTTPException(422, "radius_miles needs near_lat and near_lng")
        self.point = (near_lat, near_lng) if near_lat is not None else None
        self.radius = radius_miles

    def miles(self):
        """Haversine distance to each event, as a SQL expression."""
        lat, lng = self.point
        dlat = func.radians(LocalEvent.latitude - lat)
        dlng = func.radians(LocalEvent.longitude - lng)
        a = func.power(func.sin(dlat / 2), 2) + func.cos(func.radians(lat)) * func.cos(func.radians(LocalEvent.latitude)) * func.power(func.sin(dlng / 2), 2)
        # LEAST guards asin against 1.0000000002, but it also skips NULLs -
        # without the CASE an unplaced event came out 12,437 miles away.
        placed = and_(LocalEvent.latitude.is_not(None), LocalEvent.longitude.is_not(None))
        return case((placed, 3958.8 * 2 * func.asin(func.sqrt(func.least(1.0, a)))), else_=None)

    def conds(self) -> list:
        if self.point is None or self.radius is None:
            return []
        return [or_(LocalEvent.latitude.is_(None), LocalEvent.longitude.is_(None), self.miles() <= self.radius)]


_LOCAL_TZ = ZoneInfo("America/New_York")

# Anonymous and identical for every visitor with the same filters (the page
# opens on today, near Cherry Hill), and the feed only changes when the
# refresh job runs. 0 disables it; the test suite does.
_CACHE = SingleFlightTTLCache(ttl_s=float(os.getenv("LOCAL_EVENTS_CACHE_TTL_S", "600")), max_total_bytes=16 * 1024 * 1024)
_ROWS_ADAPTER = TypeAdapter(LocalEventRowsOut)
_DAYS_ADAPTER = TypeAdapter(LocalEventDaysOut)
# A year of the feed was ~10k events (2026); a month ~5k.
_MAX_ROWS = 6000


def date_keys(start: datetime, end: datetime | None, all_day: bool) -> list[date]:
    """Every Cherry Hill date an event covers - the same rule as
    frontend/src/lib/calendar.ts:itemDateKeys, which the page uses to file
    rows under days, so a dot is never drawn on a day whose list is empty.
    An all-day end is the ICS-style exclusive day after; a timed end that
    lands on a later date counts that date."""
    first = start.astimezone(_LOCAL_TZ).date()
    if end is None:
        return [first]
    last = end.astimezone(_LOCAL_TZ).date()
    if all_day:
        last -= timedelta(days=1)
    if last <= first:
        return [first]
    return [first + timedelta(days=n) for n in range((last - first).days + 1)]


def _day_bounds(day: date) -> tuple[datetime, datetime]:
    """A range whose overlap filter keeps every event date_keys files under
    `day`. One second early: a timed event ending exactly at midnight still
    counts that date, and the overlap filter wants end > start."""
    start = datetime.combine(day, dtime.min, _LOCAL_TZ)
    return start - timedelta(seconds=1), datetime.combine(day, dtime.max, _LOCAL_TZ)


def _cache_key(request: Request) -> tuple:
    # Order-insensitive, so ?a=1&b=2 and ?b=2&a=1 share one entry.
    return (request.url.path, tuple(sorted(parse_qsl(request.url.query, keep_blank_values=True))))


async def _cached(request: Request, q: str | None, compute, adapter: TypeAdapter, db: AsyncSession):
    """The response, from the cache when one is held for this exact query.
    Text searches are too varied to be worth holding."""
    if not _CACHE.enabled or q:
        return await compute(db)

    async def body() -> bytes:
        # Its own session: other visitors wait on this same computation.
        async with database.SessionLocal() as own_db:
            return adapter.dump_json(await compute(own_db))

    return Response(content=await _CACHE.get_or_compute(_cache_key(request), body), media_type="application/json")


def _filters(start, end, q, categories, source, is_free) -> list:
    # A Localz provider's posted date shows only while its listing does: a
    # listing a reviewer hid (or that went inactive) takes its dates with it.
    conds = [
        or_(
            LocalEvent.resource_service_id.is_(None),
            LocalEvent.resource_service_id.in_(select(ResourceService.id).where(ResourceService.status == "active")),
        )
    ]
    if start is not None:
        # Overlapping the range, like /calendar: a multi-day event that began
        # before the range but is still running counts.
        conds.append(or_(LocalEvent.start_time >= start, LocalEvent.end_time > start))
    if end is not None:
        conds.append(LocalEvent.start_time <= end)
    if q:
        # Whitespace tokens AND together, each matching any text field.
        for token in q.split():
            like = f"%{fold(token)}%"
            conds.append(
                or_(folded(LocalEvent.title).like(like), folded(LocalEvent.description).like(like), folded(LocalEvent.venue_name).like(like), folded(LocalEvent.venue_address).like(like))
            )
    if categories:
        cats = [c.strip() for c in categories.split(",") if c.strip()]
        if cats:
            conds.append(LocalEvent.categories.op("&&")(cats))
    if source:
        conds.append(LocalEvent.source == source)
    if is_free is not None:
        conds.append(LocalEvent.is_free.is_(is_free))
    return conds


@router.get("", response_model=LocalEventListOut)
async def list_local_events(
    db: AsyncSession = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    q: str | None = Query(None, max_length=200),
    categories: str | None = Query(None, description="Comma-separated; any match"),
    source: str | None = None,
    is_free: bool | None = None,
    limit: int = Query(1000, ge=1, le=3000),
    offset: int = Query(0, ge=0),
    near: Near = Depends(),
):
    conds = _filters(start, end, q, categories, source, is_free) + near.conds()
    stmt = select(LocalEvent).where(and_(*conds)) if conds else select(LocalEvent)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    if near.point is not None:
        stmt = stmt.add_columns(near.miles().label("miles"))
    rows = (await db.execute(stmt.order_by(LocalEvent.start_time, LocalEvent.title).limit(limit).offset(offset))).all()
    items = []
    for row in rows:
        item = LocalEventOut.model_validate(row[0])
        if near.point is not None and row[1] is not None:
            item.miles = round(row[1], 1)
        items.append(item)
    return LocalEventListOut(items=items, total=total)


@router.get("/rows", response_model=LocalEventRowsOut)
async def list_local_event_rows(
    request: Request,
    db: AsyncSession = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    day: date | None = Query(None, description="Only events on this Cherry Hill date (overrides start/end)"),
    q: str | None = Query(None, max_length=200),
    categories: str | None = Query(None, description="Comma-separated; any match"),
    source: str | None = None,
    is_free: bool | None = None,
    limit: int = Query(500, ge=1, le=_MAX_ROWS),
    offset: int = Query(0, ge=0),
    near: Near = Depends(),
):
    """The /local page's list, in light rows. `day` gives exactly the events
    filed under that date, the same ones its dot on /days counts."""
    if day is not None:
        start, end = _day_bounds(day)

    async def compute(session: AsyncSession) -> LocalEventRowsOut:
        conds = _filters(start, end, q, categories, source, is_free) + near.conds()
        cols = [getattr(LocalEvent, f) for f in LocalEventRowOut.model_fields if f != "miles"]
        stmt = select(*cols).where(and_(*conds))
        if near.point is not None:
            stmt = stmt.add_columns(near.miles().label("miles"))
        stmt = stmt.order_by(LocalEvent.start_time, LocalEvent.title)
        if day is not None:
            # One day is small: filter by date_keys in full, then page.
            rows = [r for r in (await session.execute(stmt)).all() if day in date_keys(r.start_time, r.end_time, r.all_day)]
            total, rows = len(rows), rows[offset : offset + limit]
        else:
            total = (await session.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
            rows = (await session.execute(stmt.limit(limit).offset(offset))).all()
        items = []
        for r in rows:
            item = LocalEventRowOut.model_validate(r._mapping)
            if near.point is not None and r.miles is not None:
                item.miles = round(r.miles, 1)
            items.append(item)
        return LocalEventRowsOut(items=items, total=total)

    return await _cached(request, q, compute, _ROWS_ADAPTER, db)


@router.get("/days", response_model=LocalEventDaysOut)
async def local_event_days(
    request: Request,
    start: datetime,
    end: datetime,
    db: AsyncSession = Depends(get_db),
    q: str | None = Query(None, max_length=200),
    categories: str | None = Query(None, description="Comma-separated; any match"),
    source: str | None = None,
    is_free: bool | None = None,
    near: Near = Depends(),
):
    """How many events fall on each date in the range, for the month and
    year grids' dots - so a grid no longer needs every event of the month
    (a busy month ran past the list's cap and lost its last ten days)."""
    # A bare timestamp is UTC, as the page's toISOString() sends.
    start, end = (t if t.tzinfo else t.replace(tzinfo=UTC) for t in (start, end))
    if end - start > timedelta(days=400):
        raise HTTPException(422, "start..end may span at most 400 days")
    first, last = start.astimezone(_LOCAL_TZ).date(), end.astimezone(_LOCAL_TZ).date()

    async def compute(session: AsyncSession) -> LocalEventDaysOut:
        conds = _filters(start, end, q, categories, source, is_free) + near.conds()
        rows = (await session.execute(select(LocalEvent.start_time, LocalEvent.end_time, LocalEvent.all_day).where(and_(*conds)))).all()
        days: dict[str, int] = defaultdict(int)
        for r in rows:
            for d in date_keys(r.start_time, r.end_time, r.all_day):
                if first <= d <= last:
                    days[d.isoformat()] += 1
        return LocalEventDaysOut(days=dict(sorted(days.items())), total=len(rows))

    return await _cached(request, q, compute, _DAYS_ADAPTER, db)


@router.post("/place", response_model=PlaceOut)
async def find_a_place(body: PlaceIn, request: Request):
    """An address, town or ZIP as a point, for "events near ...". A POST so
    what someone typed - quite possibly their home address - travels in the
    body, not in a URL that access logs and RUM record. Nothing about the
    lookup is stored; the page keeps the answer in the browser."""
    ip = client_ip(request) or "unknown"
    now = time.monotonic()
    window = _place_requests_by_ip[ip]
    while window and now - window[0] > _PLACE_WINDOW_SECONDS:
        window.popleft()
    if len(window) >= _PLACE_MAX_PER_WINDOW:
        raise HTTPException(429, "Too many lookups - please wait a few minutes and try again.")
    window.append(now)
    try:
        async with httpx.AsyncClient(timeout=8.0) as client:
            place = await find_place(client, body.q)
    except httpx.HTTPError:
        raise HTTPException(503, "Couldn't look that up right now - please try again.") from None
    if place is None:
        raise HTTPException(404, "Couldn't find that place - try a street address with the town, or a ZIP code.")
    return PlaceOut(label=place.label, latitude=place.latitude, longitude=place.longitude)


@router.get("/facets", response_model=LocalEventFacetsOut)
async def local_event_facets(
    db: AsyncSession = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    near: Near = Depends(),
):
    """Category and source counts for the filter menus, over the same range
    and radius the page is showing - so a menu never offers something with
    nothing behind it."""
    conds = _filters(start, end, None, None, None, None) + near.conds()
    where = and_(*conds) if conds else True
    cat = func.unnest(LocalEvent.categories).label("value")
    cat_rows = (await db.execute(select(cat, func.count()).where(where).group_by("value").order_by(func.count().desc()))).all()
    src_rows = (
        await db.execute(select(LocalEvent.source, func.count()).where(where).group_by(LocalEvent.source).order_by(func.count().desc()))
    ).all()
    return LocalEventFacetsOut(
        categories=[FacetOut(value=v, count=c) for v, c in cat_rows],
        sources=[FacetOut(value=v, count=c) for v, c in src_rows],
    )


@router.get("/{event_id}", response_model=LocalEventOut)
async def get_local_event(event_id: str = Path(max_length=64), db: AsyncSession = Depends(get_db)):
    """One event by its id, for an app that keeps ids (billz adds an event to
    its family calendar by id). Shown on the same terms as the list, so a
    hidden listing's posted date is not found here either. Registered last so
    `/facets` is never read as an id."""
    conds = _filters(None, None, None, None, None, None)
    event = (await db.execute(select(LocalEvent).where(LocalEvent.id == event_id, *conds))).scalar_one_or_none()
    if event is None:
        raise HTTPException(404, "No such event")
    return LocalEventOut.model_validate(event)
