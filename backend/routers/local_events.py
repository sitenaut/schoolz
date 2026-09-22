"""Read API for the local events feed (/local). Signed-in users only - this
is community data pulled from third-party feeds, not school data, so it
isn't part of the public-by-default surface."""

from datetime import datetime

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import and_, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user
from database import get_db
from models import LocalEvent, User

router = APIRouter(prefix="/local-events", tags=["local-events"])


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

    model_config = {"from_attributes": True}


class LocalEventListOut(BaseModel):
    items: list[LocalEventOut]
    total: int


class FacetOut(BaseModel):
    value: str
    count: int


class LocalEventFacetsOut(BaseModel):
    categories: list[FacetOut]
    sources: list[FacetOut]


def _filters(start, end, q, categories, source, is_free) -> list:
    conds = []
    if start is not None:
        # Overlapping the range, like /calendar: a multi-day event that began
        # before the range but is still running counts.
        conds.append(or_(LocalEvent.start_time >= start, LocalEvent.end_time > start))
    if end is not None:
        conds.append(LocalEvent.start_time <= end)
    if q:
        # Whitespace tokens AND together, each matching any text field.
        for token in q.split():
            like = f"%{token}%"
            conds.append(
                or_(LocalEvent.title.ilike(like), LocalEvent.description.ilike(like), LocalEvent.venue_name.ilike(like), LocalEvent.venue_address.ilike(like))
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
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
    q: str | None = Query(None, max_length=200),
    categories: str | None = Query(None, description="Comma-separated; any match"),
    source: str | None = None,
    is_free: bool | None = None,
    limit: int = Query(1000, ge=1, le=3000),
    offset: int = Query(0, ge=0),
):
    conds = _filters(start, end, q, categories, source, is_free)
    stmt = select(LocalEvent).where(and_(*conds)) if conds else select(LocalEvent)
    total = (await db.execute(select(func.count()).select_from(stmt.subquery()))).scalar_one()
    rows = (await db.execute(stmt.order_by(LocalEvent.start_time, LocalEvent.title).limit(limit).offset(offset))).scalars().all()
    return LocalEventListOut(items=[LocalEventOut.model_validate(r) for r in rows], total=total)


@router.get("/facets", response_model=LocalEventFacetsOut)
async def local_event_facets(
    _: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    start: datetime | None = None,
    end: datetime | None = None,
):
    """Category and source counts for the filter menus, over the same range
    the page is showing - so a menu never offers something with nothing
    behind it."""
    conds = _filters(start, end, None, None, None, None)
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
