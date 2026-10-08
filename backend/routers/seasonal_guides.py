"""Seasonal guides - links to other people's seasonal resources (a Halloween
house map, fall-festival roundups) behind the top-bar season badge.

Reads are public, like the rest of the community layer. Writes are admin
(`seasonal.manage`). Links only - see models.SeasonalGuide."""

from datetime import date, datetime
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, HTTPException, Query, Response, status
from pydantic import BaseModel, HttpUrl, model_validator
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_permission
from database import get_db
from models import SeasonalGuide, User

router = APIRouter(prefix="/seasonal-guides", tags=["seasonal-guides"])

ET = ZoneInfo("America/New_York")


class SeasonalGuideOut(BaseModel):
    id: str
    season: str
    title: str
    publisher: str
    url: str
    note: str | None
    starts_on: date
    ends_on: date
    sort_order: int

    model_config = {"from_attributes": True}


class SeasonalGuideIn(BaseModel):
    season: str
    title: str
    publisher: str
    url: HttpUrl
    note: str | None = None
    starts_on: date
    ends_on: date
    sort_order: int = 0

    @model_validator(mode="after")
    def _window(self):
        if self.ends_on < self.starts_on:
            raise ValueError("ends_on is before starts_on")
        self.season = self.season.strip().lower()
        return self


class SeasonalGuidePatch(BaseModel):
    season: str | None = None
    title: str | None = None
    publisher: str | None = None
    url: HttpUrl | None = None
    note: str | None = None
    starts_on: date | None = None
    ends_on: date | None = None
    sort_order: int | None = None


def today_et() -> date:
    return datetime.now(ET).date()


async def active_guides(db: AsyncSession, season: str | None = None, on: date | None = None) -> list[SeasonalGuide]:
    """Guides whose window includes `on` (today in Eastern by default),
    grouped by season, headline first. Shared with the MCP tool."""
    on = on or today_et()
    stmt = select(SeasonalGuide).where(SeasonalGuide.starts_on <= on, SeasonalGuide.ends_on >= on)
    if season:
        stmt = stmt.where(SeasonalGuide.season == season.strip().lower())
    stmt = stmt.order_by(SeasonalGuide.season, SeasonalGuide.sort_order, SeasonalGuide.title)
    return list((await db.execute(stmt)).scalars().all())


@router.get("", response_model=list[SeasonalGuideOut])
async def list_active(season: str | None = Query(None), db: AsyncSession = Depends(get_db)):
    return await active_guides(db, season)


@router.get("/all", response_model=list[SeasonalGuideOut])
async def list_all(_: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)):
    stmt = select(SeasonalGuide).order_by(SeasonalGuide.starts_on.desc(), SeasonalGuide.season, SeasonalGuide.sort_order)
    return (await db.execute(stmt)).scalars().all()


@router.post("", response_model=SeasonalGuideOut, status_code=status.HTTP_201_CREATED)
async def create(body: SeasonalGuideIn, _: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)):
    row = SeasonalGuide(**body.model_dump(exclude={"url"}), url=str(body.url))
    db.add(row)
    await db.commit()
    await db.refresh(row)
    return row


async def _get(db: AsyncSession, guide_id: str) -> SeasonalGuide:
    row = await db.get(SeasonalGuide, guide_id)
    if not row:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Guide not found")
    return row


@router.patch("/{guide_id}", response_model=SeasonalGuideOut)
async def update(
    guide_id: str, body: SeasonalGuidePatch, _: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)
):
    row = await _get(db, guide_id)
    for field, value in body.model_dump(exclude_unset=True).items():
        if field == "url" and value is not None:
            value = str(value)
        elif field == "season" and value is not None:
            value = value.strip().lower()
        setattr(row, field, value)
    if row.ends_on < row.starts_on:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "ends_on is before starts_on")
    await db.commit()
    await db.refresh(row)
    return row


@router.delete("/{guide_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete(guide_id: str, _: User = Depends(require_permission("seasonal.manage")), db: AsyncSession = Depends(get_db)):
    await db.delete(await _get(db, guide_id))
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)
