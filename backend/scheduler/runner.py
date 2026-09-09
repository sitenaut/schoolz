import asyncio
import hashlib
import traceback
from datetime import datetime, timezone

from croniter import croniter
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

from database import SessionLocal
from models import JobRun, ScheduledJob
from scheduler.registry import registry

_ADVISORY_LOCK_NAMESPACE = 42


async def _try_advisory_lock(db: AsyncSession, job_id_int: int) -> bool:
    result = await db.execute(
        text("SELECT pg_try_advisory_lock(:ns, :job_id)"), {"ns": _ADVISORY_LOCK_NAMESPACE, "job_id": job_id_int}
    )
    return bool(result.scalar())


async def _release_advisory_lock(db: AsyncSession, job_id_int: int) -> None:
    await db.execute(
        text("SELECT pg_advisory_unlock(:ns, :job_id)"), {"ns": _ADVISORY_LOCK_NAMESPACE, "job_id": job_id_int}
    )


def _lock_key(job_id: str) -> int:
    # Postgres advisory locks take a bigint - fold the string uuid down to
    # a stable int. MUST be deterministic across processes (the API process
    # and the separate scheduler process both compute this for the same
    # job_id and need to agree) - Python's built-in hash() is randomized
    # per-process for strings, so it cannot be used here.
    digest = hashlib.sha256(job_id.encode()).digest()
    return int.from_bytes(digest[:4], "big") % (2**31)


async def _finalize(job_id: str, run_id: str, *, status: str, error: str | None, log_excerpt: str | None, started_at: datetime) -> None:
    async with SessionLocal() as db:
        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)

        run = (await db.execute(select(JobRun).where(JobRun.id == run_id))).scalar_one_or_none()
        if run:
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = duration_ms
            run.error = error
            run.log_excerpt = log_excerpt

        job = (await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))).scalar_one_or_none()
        if job:
            job.last_run_at = started_at
            job.last_status = status
            job.last_error = error
            job.last_duration_ms = duration_ms
            if job.enabled:
                try:
                    tz = ZoneInfo(job.timezone)
                    job.next_run_at = croniter(job.cron_expr, datetime.now(tz)).get_next(datetime)
                except Exception:
                    job.next_run_at = None
        await db.commit()


async def _execute(job_id: str, *, triggered_by: str) -> None:
    started_at = datetime.now(timezone.utc)
    lock_key = _lock_key(job_id)

    async with SessionLocal() as db:
        locked = await _try_advisory_lock(db, lock_key)
        if not locked:
            run = JobRun(job_id=job_id, status="skipped", triggered_by=triggered_by, finished_at=datetime.now(timezone.utc))
            db.add(run)
            await db.commit()
            return

        try:
            job = (await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))).scalar_one_or_none()
            if not job:
                return
            spec = registry.get(job.kind)
            if not spec:
                run = JobRun(job_id=job_id, status="error", triggered_by=triggered_by, error=f"Unknown job kind: {job.kind}")
                db.add(run)
                await db.commit()
                return

            run = JobRun(job_id=job_id, status="running", triggered_by=triggered_by)
            db.add(run)
            job.last_status = "running"
            await db.commit()
            await db.refresh(run)
            run_id = run.id

            try:
                log_excerpt = await spec.handler(db, dict(job.params or {}))
                await db.commit()
                # A handler signals a non-fatal partial result (e.g. "found
                # the site but no address on it") by prefixing its returned
                # message with "WARNING:" - it didn't raise, so it isn't an
                # "error", but silently calling it "success" would hide
                # exactly the kind of gap this scan exists to catch.
                run_status = "warning" if log_excerpt and log_excerpt.startswith("WARNING:") else "success"
                await _finalize(job_id, run_id, status=run_status, error=None, log_excerpt=log_excerpt, started_at=started_at)
            except Exception as exc:
                await db.rollback()
                await _finalize(
                    job_id,
                    run_id,
                    status="error",
                    error=f"{type(exc).__name__}: {exc}",
                    log_excerpt=traceback.format_exc()[-4000:],
                    started_at=started_at,
                )
        finally:
            await _release_advisory_lock(db, lock_key)
            await db.commit()


# asyncio only holds a weak reference to tasks created via create_task - with
# nothing else referencing this fire-and-forget task, it can be garbage
# collected mid-run, abandoning the DB session before its `finally` releases
# the Postgres advisory lock (leaking it on that pooled connection forever).
_background_tasks: set[asyncio.Task] = set()


def run_job_now(job_id: str) -> None:
    """Fire-and-forget: schedules the run on the current event loop and
    returns immediately. Result shows up later via GET .../runs."""
    task = asyncio.create_task(_execute(job_id, triggered_by="manual"))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)


def build_apscheduler_job(scheduler, job: ScheduledJob) -> None:
    from apscheduler.triggers.cron import CronTrigger

    apscheduler_job_id = f"job-{job.id}"
    existing = scheduler.get_job(apscheduler_job_id)
    if existing:
        scheduler.remove_job(apscheduler_job_id)
    if not job.enabled:
        return

    trigger = CronTrigger.from_crontab(job.cron_expr, timezone=ZoneInfo(job.timezone))
    scheduler.add_job(
        _execute,
        trigger=trigger,
        id=apscheduler_job_id,
        kwargs={"job_id": job.id, "triggered_by": "cron"},
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
