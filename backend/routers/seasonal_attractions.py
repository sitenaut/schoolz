"""Seasonal attractions - haunts, flashlight mazes, light shows, Santa: places
open for a season (models.SeasonalAttraction). Reads are public; writes are
admin (`seasonal.manage`), the same as seasonal guides."""

import math
from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, HttpUrl, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_permission
from database import get_db
from models import SeasonalAttraction, User
from routers.seasonal_guides import today_et

router = APIRouter(prefix="/seasonal-attractions", tags=["seasonal-attractions"])

SCARE_LEVELS = {"family", "mild", "scary"}


class SeasonalAttractionOut(BaseModel):
    id: str
    season: str
    kind: str
    name: str
    venue: str | None
    address: str
    town: str
    latitude: float | None
    longitude: float | None
    url: str
    ticket_url: str | None
    starts_on: date
    ends_on: date
    open_dates: list[date] | None
    schedule: str | None
    price: str | None
    scare_level: str | None
    ages: str | None
    note: str | None
    source_url: str | None
    verified_on: date | None
    # Filled per request: whether it's open on the day asked about (true,
    # false, or null = the venue hasn't said which nights), and how far it is
    # from the point given.
    open_on_day: bool | None = None
    miles: float | None = None

    model_config = {"from_attributes": True}


class SeasonalAttractionIn(BaseModel):
    season: str
    kind: str
    name: str
    venue: str | None = None
    address: str
    town: str
    latitude: float | None = None
    longitude: float | None = None
    url: HttpUrl
    ticket_url: HttpUrl | None = None
    starts_on: date
    ends_on: date
    open_dates: list[date] | None = None
    schedule: str | None = None
    price: str | None = None
    scare_level: str | None = None
    ages: str | None = None
    note: str | None = None
    source_url: HttpUrl | None = None
    verified_on: date | None = None

    @model_validator(mode="after")
    def _check(self):
        _validate(self.starts_on, self.ends_on, self.open_dates, self.scare_level)
        self.season = self.season.strip().lower()
        return self


class SeasonalAttractionPatch(BaseModel):
    season: str | None = None
    kind: str | None = None
    name: str | None = None
    venue: str | None = None
    address: str | None = None
    town: str | None = None
    latitude: float | None = None
    longitude: float | None = None
    url: HttpUrl | None = None
    ticket_url: HttpUrl | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    open_dates: list[date] | None = None
    schedule: str | None = None
    price: str | None = None
    scare_level: str | None = None
    ages: str | None = None
    note: str | None = None
    source_url: HttpUrl | None = None
    verified_on: date | None = None


def _validate(starts_on: date, ends_on: date, open_dates: list[date] | None, scare_level: str | None) -> None:
    if ends_on < starts_on:
        raise ValueError("ends_on is before starts_on")
    if open_dates and any(d < starts_on or d > ends_on for d in open_dates):
        raise ValueError("an open date falls outside starts_on..ends_on")
    if scare_level is not None and scare_level not in SCARE_LEVELS:
        raise ValueError(f"scare_level must be one of {sorted(SCARE_LEVELS)}")


def miles_between(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    p1, p2 = math.radians(lat1), math.radians(lat2)
    a = math.sin((p2 - p1) / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(math.radians(lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(a))


def open_on(row: SeasonalAttraction, day: date) -> bool | None:
    """True/False when the venue publishes its nights; None when it only gives
    a window ("select nights"), so nobody is told a place is open when it
    might not be."""
    if day < row.starts_on or day > row.ends_on:
        return False
    if row.open_dates is None:
        return None
    return day in row.open_dates


async def find_attractions(
    db: AsyncSession,
    season: str | None = None,
    kind: str | None = None,
    scare_level: str | None = None,
    day: date | None = None,
    open_only: bool = False,
    near: tuple[float, float] | None = None,
    max_miles: float | None = None,
) -> list[SeasonalAttractionOut]:
    """Attractions still running on `day` (today in Eastern by default):
    already open or opening later this season. `open_only` keeps the ones
    open that day or that might be. Nearest first when `near` is given,
    else soonest first."""
    day = day or today_et()
    stmt = select(SeasonalAttraction).where(SeasonalAttraction.ends_on >= day)
    if season:
        stmt = stmt.where(SeasonalAttraction.season == season.strip().lower())
    if kind:
        stmt = stmt.where(SeasonalAttraction.kind == kind)
    if scare_level:
        stmt = stmt.where(SeasonalAttraction.scare_level == scare_level)
    out = []
    for row in (await db.execute(stmt)).scalars().all():
        item = SeasonalAttractionOut.model_validate(row)
        item.open_on_day = open_on(row, day)
        if open_only and item.open_on_day is False:
            continue
        if near and row.latitude is not None and row.longitude is not None:
            item.miles = round(miles_between(near[0], near[1], row.latitude, row.longitude), 1)
            if max_miles is not None and item.miles > max_miles:
                continue
        out.append(item)
    if near:
        out.sort(key=lambda a: (a.miles is None, a.miles or 0, a.name))
    else:
        out.sort(key=lambda a: (a.starts_on, a.name))
    return out


@router.get("", response_model=list[SeasonalAttractionOut])
async def list_attractions(
    season: str | None = Query(None),
    kind: str | None = Query(None),
    scare_level: str | None = Query(None),
    on: date | None = Query(None, description="The day asked about; today in Eastern by default."),
    open_only: bool = Query(False, description="Only those open on `on` (or that may be)."),
    near_lat: float | None = Query(None),
    near_lng: float | None = Query(None),
    max_miles: float | None = Query(None),
    db: AsyncSession = Depends(get_db),
):
    near = (near_lat, near_lng) if near_lat is not None and near_lng is not None else None
    return await find_attractions(db, season, kind, scare_level, on, open_only, near, max_miles)


@router.get("/all", response_model=list[SeasonalAttractionOut])
async def list_all(_: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)):
    stmt = select(SeasonalAttraction).order_by(SeasonalAttraction.starts_on.desc(), SeasonalAttraction.name)
    return (await db.execute(stmt)).scalars().all()


def _plain(data: dict) -> dict:
    """HttpUrl -> str, season lower-cased, for writing to the row."""
    for key in ("url", "ticket_url", "source_url"):
        if data.get(key) is not None:
            data[key] = str(data[key])
    if data.get("season") is not None:
        data["season"] = data["season"].strip().lower()
    return data


@router.post("", response_model=SeasonalAttractionOut, status_code=status.HTTP_201_CREATED)
async def create(body: SeasonalAttractionIn, _: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)):
    row = SeasonalAttraction(**_plain(body.model_dump()))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get(db: AsyncSession, attraction_id: str) -> SeasonalAttraction:
    row = await db.get(SeasonalAttraction, attraction_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Attraction not found")
    return row


@router.patch("/{attraction_id}", response_model=SeasonalAttractionOut)
async def update(
    attraction_id: str,
    body: SeasonalAttractionPatch,
    _: User = Depends(require_permission("seasonal.manage")),
    db: AsyncSession = Depends(get_db),
):
    row = await _get(db, attraction_id)
    for field, value in _plain(body.model_dump(exclude_unset=True)).items():
        setattr(row, field, value)
    try:
        _validate(row.starts_on, row.ends_on, row.open_dates, row.scare_level)
    except ValueError as e:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, str(e)) from None
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{attraction_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(attraction_id: str, _: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)):
    await db.delete(await _get(db, attraction_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
