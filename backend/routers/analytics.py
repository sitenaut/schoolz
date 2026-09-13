import re
import uuid
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Depends, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import CommunitySubmission, PageVisit, SurveyResponse, User

router = APIRouter(prefix="/page-views", tags=["analytics"])

_SCHOOL_TZ = ZoneInfo("America/New_York")

# Only the public pages worth measuring. An allowlist rather than "record
# whatever the client sends" keeps the table bounded and stops it being
# turned into a scratchpad by anyone who finds the endpoint.
_TRACKED_PATHS = {"/", "/chcomms", "/survey", "/schools", "/calendar", "/lunch", "/contact", "/start", "/privacy"}

_SOURCE_RE = re.compile(r"^[a-z0-9][a-z0-9.\-]{0,39}$")


def _today() -> str:
    return datetime.now(_SCHOOL_TZ).strftime("%Y-%m-%d")


def _clean_source(raw: str | None) -> str:
    """Normalized server-side rather than trusted: the client picks the
    label, but an arbitrary string would let anyone widen this column into
    free-form storage."""
    value = (raw or "").strip().lower()[:40]
    if not value or not _SOURCE_RE.match(value):
        return "other"
    return value


class PageViewIn(BaseModel):
    path: str = Field(max_length=100)
    source: str | None = Field(default=None, max_length=40)


@router.post("", status_code=status.HTTP_204_NO_CONTENT)
async def record_page_view(payload: PageViewIn, db: AsyncSession = Depends(get_db)) -> Response:
    """Public, unauthenticated, and intentionally boring: it increments one
    counter and returns nothing. Nothing identifying is accepted or stored -
    see the PageVisit model docstring."""
    if payload.path not in _TRACKED_PATHS:
        # Not an error worth surfacing to a browser beacon - just ignore it.
        return Response(status_code=status.HTTP_204_NO_CONTENT)

    day = _today()
    source = _clean_source(payload.source)
    statement = (
        pg_insert(PageVisit)
        .values(id=str(uuid.uuid4()), day=day, path=payload.path, source=source, count=1)
        .on_conflict_do_update(
            constraint="uq_page_visits_day_path_source",
            set_={"count": PageVisit.__table__.c.count + 1, "updated_at": datetime.now(_SCHOOL_TZ)},
        )
    )
    await db.execute(statement)
    await db.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


class PageVisitRow(BaseModel):
    day: str
    path: str
    source: str
    count: int


class PageVisitReport(BaseModel):
    rows: list[PageVisitRow]
    totals_by_path: dict[str, int]
    totals_by_source: dict[str, int]


@router.get("", response_model=PageVisitReport)
async def read_page_views(
    days: int = 30, _: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
) -> PageVisitReport:
    since = (datetime.now(_SCHOOL_TZ) - timedelta(days=max(1, min(days, 365)))).strftime("%Y-%m-%d")
    result = await db.execute(
        select(PageVisit).where(PageVisit.day >= since).order_by(PageVisit.day.desc(), PageVisit.count.desc())
    )
    rows = result.scalars().all()

    totals_by_path: dict[str, int] = {}
    totals_by_source: dict[str, int] = {}
    for row in rows:
        totals_by_path[row.path] = totals_by_path.get(row.path, 0) + row.count
        totals_by_source[row.source] = totals_by_source.get(row.source, 0) + row.count

    return PageVisitReport(
        rows=[PageVisitRow(day=r.day, path=r.path, source=r.source, count=r.count) for r in rows],
        totals_by_path=dict(sorted(totals_by_path.items(), key=lambda kv: -kv[1])),
        totals_by_source=dict(sorted(totals_by_source.items(), key=lambda kv: -kv[1])),
    )


class DayVisits(BaseModel):
    day: str
    visits: int


class CampaignReport(BaseModel):
    """The shape of the report that's actually useful to look at, as
    opposed to PageVisitReport above (the raw day/path/source rows) - built
    because this exact set of numbers kept getting hand-queried by SQL
    every time someone asked "how's the campaign doing" and deserved a
    real page instead."""

    total_visits: int
    visits_today: int
    visits_yesterday: int
    by_source: dict[str, int]
    chcomms_reads: int
    survey_opened: int
    survey_completed: int
    start_page_visits: int
    newsletters_submitted: int
    newsletters_pending: int
    by_day: list[DayVisits]


async def _path_total(db: AsyncSession, path: str) -> int:
    result = await db.execute(select(func.coalesce(func.sum(PageVisit.count), 0)).where(PageVisit.path == path))
    return result.scalar_one()


@router.get("/campaign-report", response_model=CampaignReport)
async def campaign_report(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> CampaignReport:
    today = _today()
    yesterday = (datetime.now(_SCHOOL_TZ) - timedelta(days=1)).strftime("%Y-%m-%d")

    total_visits = (await db.execute(select(func.coalesce(func.sum(PageVisit.count), 0)))).scalar_one()

    by_day_rows = (
        await db.execute(
            select(PageVisit.day, func.sum(PageVisit.count)).group_by(PageVisit.day).order_by(PageVisit.day)
        )
    ).all()
    by_day = {day: int(visits) for day, visits in by_day_rows}

    by_source_rows = (
        await db.execute(select(PageVisit.source, func.sum(PageVisit.count)).group_by(PageVisit.source))
    ).all()
    by_source = dict(sorted(((source, int(visits)) for source, visits in by_source_rows), key=lambda kv: -kv[1]))

    survey_completed = (await db.execute(select(func.count()).select_from(SurveyResponse))).scalar_one()
    newsletters_submitted = (await db.execute(select(func.count()).select_from(CommunitySubmission))).scalar_one()
    newsletters_pending = (
        await db.execute(
            select(func.count()).select_from(CommunitySubmission).where(CommunitySubmission.status == "pending")
        )
    ).scalar_one()

    return CampaignReport(
        total_visits=int(total_visits),
        visits_today=by_day.get(today, 0),
        visits_yesterday=by_day.get(yesterday, 0),
        by_source=by_source,
        chcomms_reads=await _path_total(db, "/chcomms"),
        survey_opened=await _path_total(db, "/survey"),
        survey_completed=survey_completed,
        start_page_visits=await _path_total(db, "/start"),
        newsletters_submitted=newsletters_submitted,
        newsletters_pending=newsletters_pending,
        by_day=[DayVisits(day=day, visits=visits) for day, visits in sorted(by_day.items())],
    )
