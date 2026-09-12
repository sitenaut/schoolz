from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from croniter import croniter
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import District, EmailScanner, JobRun, ScheduledJob, School, SmoreNewsletter, User
from schemas import JobKindOut, JobRunOut, JobRunSummaryOut, ScheduledJobCreate, ScheduledJobOut, ScheduledJobUpdate
from scheduler.registry import registry

router = APIRouter(prefix="/scheduled-jobs", tags=["scheduled-jobs"])

# Which params key names a job's "target", and what to look it up in. A
# job's params are otherwise opaque handler config - this is just enough
# to put a human name on a row in the jobs table.
_TARGET_PARAMS = ("school_id", "district_id", "newsletter_id", "scanner_id")


def _validate_cron(cron_expr: str) -> None:
    if not croniter.is_valid(cron_expr):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Invalid cron expression: {cron_expr}")


def _validate_timezone(tz: str) -> None:
    try:
        ZoneInfo(tz)
    except (ZoneInfoNotFoundError, ValueError):
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown timezone: {tz}")


def _validate_params(kind: str, params: dict) -> None:
    spec = registry.get(kind)
    if not spec:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Unknown job kind: {kind}")
    schema = spec.param_schema or {}
    missing = [key for key in schema.get("required", []) if not params.get(key)]
    if missing:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Missing required params for {kind}: {', '.join(missing)}")


async def _attach_targets(db: AsyncSession, jobs: list[ScheduledJob]) -> list[ScheduledJobOut]:
    ids: dict[str, set[str]] = {key: set() for key in _TARGET_PARAMS}
    for job in jobs:
        for key in _TARGET_PARAMS:
            value = (job.params or {}).get(key)
            if value:
                ids[key].add(value)

    labels: dict[tuple[str, str], str] = {}
    if ids["school_id"]:
        rows = await db.execute(select(School.id, School.short_name, School.name).where(School.id.in_(ids["school_id"])))
        for sid, short_name, name in rows.all():
            labels[("school", sid)] = short_name or name
    if ids["district_id"]:
        rows = await db.execute(select(District.id, District.name).where(District.id.in_(ids["district_id"])))
        for did, name in rows.all():
            labels[("district", did)] = name
    if ids["newsletter_id"]:
        rows = await db.execute(
            select(SmoreNewsletter.id, SmoreNewsletter.label, SmoreNewsletter.url).where(SmoreNewsletter.id.in_(ids["newsletter_id"]))
        )
        for nid, label, url in rows.all():
            labels[("newsletter", nid)] = label or url
    if ids["scanner_id"]:
        rows = await db.execute(select(EmailScanner.id, EmailScanner.name).where(EmailScanner.id.in_(ids["scanner_id"])))
        for scid, name in rows.all():
            labels[("scanner", scid)] = name

    out: list[ScheduledJobOut] = []
    for job in jobs:
        item = ScheduledJobOut.model_validate(job)
        params = job.params or {}
        for key, target_type in (
            ("school_id", "school"),
            ("district_id", "district"),
            ("newsletter_id", "newsletter"),
            ("scanner_id", "scanner"),
        ):
            value = params.get(key)
            if value:
                item.target_type = target_type
                item.target_label = labels.get((target_type, value)) or f"(deleted {target_type})"
                break
        out.append(item)
    return out


@router.get("/kinds", response_model=list[JobKindOut], dependencies=[Depends(require_admin)])
async def list_kinds():
    """Every registered job kind, with the param schema the create form
    needs to know which target (school/district/newsletter/scanner) to ask
    for."""
    return [
        JobKindOut(
            kind=spec.kind,
            default_name=spec.default_name,
            default_cron=spec.default_cron,
            default_timezone=spec.default_timezone,
            description=spec.description,
            param_schema=spec.param_schema,
        )
        for spec in sorted(registry.values(), key=lambda s: s.kind)
    ]


@router.get("", response_model=list[ScheduledJobOut], dependencies=[Depends(require_admin)])
async def list_jobs(kind: str | None = None, db: AsyncSession = Depends(get_db)):
    """Admin-only - this is the visibility view for every centrally-managed
    scan (district feeds, staff rosters, documents, lunch menus, Smore,
    school info, email scanners)."""
    query = select(ScheduledJob)
    if kind:
        query = query.where(ScheduledJob.kind == kind)
    query = query.order_by(ScheduledJob.kind, ScheduledJob.name)
    jobs = list((await db.execute(query)).scalars().all())
    return await _attach_targets(db, jobs)


@router.get("/runs/summary", response_model=JobRunSummaryOut, dependencies=[Depends(require_admin)])
async def runs_summary(db: AsyncSession = Depends(get_db)):
    """Current state of every enabled job, rolled up by last_status - the
    numbers for the stat tiles at the top of the jobs page."""
    rows = await db.execute(
        select(ScheduledJob.last_status, func.count()).where(ScheduledJob.enabled.is_(True)).group_by(ScheduledJob.last_status)
    )
    by_status = {(status_value or "never"): count for status_value, count in rows.all()}
    return JobRunSummaryOut(total=sum(by_status.values()), by_status=by_status)


@router.post("", response_model=ScheduledJobOut, status_code=status.HTTP_201_CREATED)
async def create_job(payload: ScheduledJobCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    _validate_params(payload.kind, payload.params)
    _validate_cron(payload.cron_expr)
    _validate_timezone(payload.timezone)

    job = ScheduledJob(
        owner_user_id=user.id,
        kind=payload.kind,
        name=payload.name,
        description=payload.description,
        cron_expr=payload.cron_expr,
        timezone=payload.timezone,
        params=payload.params,
        enabled=payload.enabled,
    )
    db.add(job)
    await db.commit()
    await db.refresh(job)
    return (await _attach_targets(db, [job]))[0]


async def _get_job_or_404(db: AsyncSession, job_id: str) -> ScheduledJob:
    result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))
    job = result.scalar_one_or_none()
    if not job:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Job not found")
    return job


@router.get("/{job_id}", response_model=ScheduledJobOut, dependencies=[Depends(require_admin)])
async def get_job(job_id: str, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(db, job_id)
    return (await _attach_targets(db, [job]))[0]


@router.patch("/{job_id}", response_model=ScheduledJobOut, dependencies=[Depends(require_admin)])
async def update_job(job_id: str, payload: ScheduledJobUpdate, db: AsyncSession = Depends(get_db)):
    job = await _get_job_or_404(db, job_id)

    if payload.cron_expr is not None:
        _validate_cron(payload.cron_expr)
        job.cron_expr = payload.cron_expr
    if payload.timezone is not None:
        _validate_timezone(payload.timezone)
        job.timezone = payload.timezone
    if payload.params is not None:
        _validate_params(job.kind, payload.params)
        job.params = payload.params
    if payload.name is not None:
        job.name = payload.name
    if payload.description is not None:
        job.description = payload.description
    if payload.enabled is not None:
        job.enabled = payload.enabled
        if not payload.enabled:
            job.next_run_at = None

    await db.commit()
    await db.refresh(job)
    return (await _attach_targets(db, [job]))[0]


@router.delete("/{job_id}", status_code=status.HTTP_204_NO_CONTENT, dependencies=[Depends(require_admin)])
async def delete_job(job_id: str, db: AsyncSession = Depends(get_db)):
    """Every *_job_id column pointing at scheduled_jobs is ON DELETE SET
    NULL, so a School/District/newsletter/scanner that owned this job keeps
    existing - it just no longer has a scan. The scheduler's 30s reconcile
    loop drops the APScheduler entry on its own."""
    job = await _get_job_or_404(db, job_id)
    await db.delete(job)
    await db.commit()


@router.get("/{job_id}/runs", response_model=list[JobRunOut], dependencies=[Depends(require_admin)])
async def list_runs(job_id: str, limit: int = Query(default=50, ge=1, le=200), db: AsyncSession = Depends(get_db)):
    await _get_job_or_404(db, job_id)
    result = await db.execute(select(JobRun).where(JobRun.job_id == job_id).order_by(JobRun.started_at.desc()).limit(limit))
    return result.scalars().all()


@router.post("/{job_id}/run-now", dependencies=[Depends(require_admin)])
async def run_now(job_id: str, db: AsyncSession = Depends(get_db)):
    """Generic manual trigger for any job, regardless of kind - the
    per-entity run-now endpoints (schools/districts/newsletters/scanners)
    still exist, this is the one the jobs table's Run button uses."""
    job = await _get_job_or_404(db, job_id)
    if job.kind not in registry:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, f"Job kind {job.kind} is not registered in this process")

    from scheduler.runner import run_job_now

    run_job_now(job.id)
    return {"status": "started"}
