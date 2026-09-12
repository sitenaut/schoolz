import csv
import hashlib
import io
import os
from collections import Counter

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import School, SurveyResponse, User
from schemas import SurveyResponseCreate, SurveyResponseOut, SurveySummaryOut

router = APIRouter(prefix="/survey", tags=["survey"])


def _client_ip(request: Request) -> str:
    """Fly puts the real client address in Fly-Client-IP; behind any other
    proxy it's the first X-Forwarded-For entry. request.client.host alone
    would just be the proxy in both cases."""
    fly_ip = request.headers.get("fly-client-ip")
    if fly_ip:
        return fly_ip.strip()
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else ""


def _ip_hash(request: Request) -> str | None:
    """A salted, one-way hash - never the address itself. Enough to tell
    two hundred responses from two hundred people apart from two hundred
    responses from one person, which is the only question this needs to
    answer. Salting with a server-side secret means the hashes can't be
    brute-forced back into addresses from the small IPv4 space."""
    ip = _client_ip(request)
    if not ip:
        return None
    salt = os.getenv("JWT_SECRET", "schoolz-survey-salt")
    return hashlib.sha256(f"{salt}:{ip}".encode()).hexdigest()


@router.post("", response_model=SurveyResponseOut, status_code=status.HTTP_201_CREATED)
async def submit_survey(payload: SurveyResponseCreate, request: Request, db: AsyncSession = Depends(get_db)):
    """Public - no account, by design. Anyone in the district can answer."""
    missing_info = (payload.missing_info or "").strip() or None
    comments = (payload.comments or "").strip() or None

    # An empty form is almost always a stray submit, not an opinion worth
    # showing the district. Picked schools alone don't count - that's just
    # the picker's default state.
    if payload.satisfaction is None and not payload.pain_points and not missing_info and not comments:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Answer at least one question before submitting")

    school_ids = list(dict.fromkeys(payload.school_ids))
    if school_ids:
        found = (await db.execute(select(School.id).where(School.id.in_(school_ids)))).scalars().all()
        unknown = set(school_ids) - set(found)
        if unknown:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Unknown school_id")

    response = SurveyResponse(
        school_ids=school_ids,
        satisfaction=payload.satisfaction,
        pain_points=payload.pain_points,
        missing_info=missing_info,
        comments=comments,
        submitter_name=(payload.submitter_name or "").strip()[:200] or None,
        submitter_email=(payload.submitter_email or "").strip()[:255] or None,
        share_consent=payload.share_consent,
        user_agent=(request.headers.get("user-agent") or "")[:400] or None,
        ip_hash=_ip_hash(request),
    )
    db.add(response)
    await db.commit()
    await db.refresh(response)
    return SurveyResponseOut(
        id=response.id,
        school_ids=response.school_ids,
        satisfaction=response.satisfaction,
        pain_points=response.pain_points,
        missing_info=response.missing_info,
        comments=response.comments,
        submitter_name=response.submitter_name,
        submitter_email=response.submitter_email,
        share_consent=response.share_consent,
        created_at=response.created_at,
    )


@router.get("/summary", response_model=SurveySummaryOut)
async def survey_summary(db: AsyncSession = Depends(get_db)):
    """Public: the survey page shows the running total back to whoever's
    filling it in ("42 neighbors have answered so far"), which is both
    honest feedback that the submit worked and a nudge to take part.
    Carries no free text and no contact details for that reason."""
    total = (await db.execute(select(func.count()).select_from(SurveyResponse))).scalar_one()
    average = (await db.execute(select(func.avg(SurveyResponse.satisfaction)))).scalar_one()
    rows = (await db.execute(select(SurveyResponse.pain_points))).scalars().all()
    counts = Counter(key for row in rows for key in (row or []))
    return SurveySummaryOut(
        total=total,
        average_satisfaction=round(float(average), 2) if average is not None else None,
        top_pain_points=[{"key": key, "count": count} for key, count in counts.most_common(20)],
    )


@router.get("/responses", response_model=list[SurveyResponseOut])
async def list_responses(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    rows = (await db.execute(select(SurveyResponse).order_by(SurveyResponse.created_at.desc()))).scalars().all()
    school_ids = {sid for row in rows for sid in (row.school_ids or [])}
    names: dict[str, str] = {}
    if school_ids:
        result = await db.execute(select(School.id, School.short_name, School.name).where(School.id.in_(school_ids)))
        names = {sid: short or name for sid, short, name in result.all()}
    return [
        SurveyResponseOut(
            id=r.id,
            school_ids=r.school_ids or [],
            school_names=[names.get(sid, sid) for sid in (r.school_ids or [])],
            satisfaction=r.satisfaction,
            pain_points=r.pain_points or [],
            missing_info=r.missing_info,
            comments=r.comments,
            submitter_name=r.submitter_name,
            submitter_email=r.submitter_email,
            share_consent=r.share_consent,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.get("/responses.csv", include_in_schema=False)
async def export_responses_csv(_: User = Depends(require_admin), db: AsyncSession = Depends(get_db)) -> Response:
    """A spreadsheet is the format this data actually gets used in - the
    point of the survey is handing the district something they can sort,
    count and read, not a JSON blob."""
    rows = (await db.execute(select(SurveyResponse).order_by(SurveyResponse.created_at.desc()))).scalars().all()
    school_ids = {sid for row in rows for sid in (row.school_ids or [])}
    names: dict[str, str] = {}
    if school_ids:
        result = await db.execute(select(School.id, School.short_name, School.name).where(School.id.in_(school_ids)))
        names = {sid: short or name for sid, short, name in result.all()}

    buffer = io.StringIO()
    writer = csv.writer(buffer)
    writer.writerow(
        [
            "submitted_at_utc",
            "schools",
            "satisfaction_1_to_5",
            "hard_to_find",
            "missing_from_our_list",
            "comments",
            "name",
            "email",
            "may_be_quoted_with_name",
            "distinct_sender_hash",
        ]
    )
    for r in rows:
        writer.writerow(
            [
                r.created_at.isoformat(),
                "; ".join(names.get(sid, sid) for sid in (r.school_ids or [])),
                r.satisfaction if r.satisfaction is not None else "",
                "; ".join(r.pain_points or []),
                r.missing_info or "",
                r.comments or "",
                r.submitter_name or "",
                r.submitter_email or "",
                "yes" if r.share_consent == "named" else "no",
                (r.ip_hash or "")[:12],
            ]
        )
    return Response(
        content=buffer.getvalue(),
        media_type="text/csv",
        headers={"Content-Disposition": 'attachment; filename="schoolz-survey-responses.csv"'},
    )
