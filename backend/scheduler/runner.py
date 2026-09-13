import asyncio
import hashlib
import logging
import os
import time
import traceback
from datetime import datetime, timezone

from croniter import croniter
from opentelemetry import trace
from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import AsyncSession
from zoneinfo import ZoneInfo

import observability
from database import SessionLocal
from models import JobRun, ScheduledJob
from scheduler.errors import classify_exception, parse_warning
from scheduler.registry import registry

_tracer = trace.get_tracer("schoolz.scheduler")
logger = logging.getLogger(__name__)

_ADVISORY_LOCK_NAMESPACE = 42

# Every job that fires opens its own DB session (below, plus another one
# in _finalize) - with dozens of independent cron jobs able to land in the
# same wall-clock minute (the 12h scan cadence), nothing previously
# stopped all of them from opening a session at once, well past what the
# shared connection budget allows (see database.py's pool_size comment).
# This caps how many jobs actually run their handler concurrently *within
# this process* - queued jobs just wait their turn rather than every one
# of them racing for a connection and getting an EMAXCONNSESSION/
# QueuePool-timeout error instead of ever running.
_concurrency_limit: asyncio.Semaphore | None = None


def _get_concurrency_limit() -> asyncio.Semaphore:
    global _concurrency_limit
    if _concurrency_limit is None:
        _concurrency_limit = asyncio.Semaphore(int(os.getenv("JOB_CONCURRENCY", "3")))
    return _concurrency_limit


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


async def _finalize(
    job_id: str,
    run_id: str,
    *,
    status: str,
    error: str | None,
    error_code: str | None,
    error_stage: str | None,
    log_excerpt: str | None,
    started_at: datetime,
) -> None:
    async with SessionLocal() as db:
        duration_ms = int((datetime.now(timezone.utc) - started_at).total_seconds() * 1000)

        run = (await db.execute(select(JobRun).where(JobRun.id == run_id))).scalar_one_or_none()
        if run:
            run.status = status
            run.finished_at = datetime.now(timezone.utc)
            run.duration_ms = duration_ms
            run.error = error
            run.error_code = error_code
            run.error_stage = error_stage
            run.log_excerpt = log_excerpt

        job = (await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))).scalar_one_or_none()
        if job:
            job.last_run_at = started_at
            job.last_status = status
            job.last_error = error
            job.last_error_code = error_code
            job.last_duration_ms = duration_ms
            if job.run_once:
                # One-shot job: this was its only run, win or lose - turn
                # it off rather than leaving it enabled to retry a URL
                # that's likely already dead (a new Smore issue replaces
                # its predecessor's URL entirely, it doesn't keep serving
                # the old one).
                job.enabled = False
                job.next_run_at = None
            elif job.enabled:
                try:
                    tz = ZoneInfo(job.timezone)
                    job.next_run_at = croniter(job.cron_expr, datetime.now(tz)).get_next(datetime)
                except Exception:
                    job.next_run_at = None
        await db.commit()


async def _execute(job_id: str, *, triggered_by: str) -> None:
    # job_kind isn't known yet (needs a DB lookup), so the queue-wait metric
    # is recorded with no job.kind attribute for the wait itself - fine,
    # since the point is the aggregate burst-queueing picture.
    wait_start = time.perf_counter()
    async with _get_concurrency_limit():
        queue_wait_s = time.perf_counter() - wait_start
        await _execute_locked(job_id, triggered_by=triggered_by, queue_wait_s=queue_wait_s)


async def _execute_locked(job_id: str, *, triggered_by: str, queue_wait_s: float = 0.0) -> None:
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
                run = JobRun(
                    job_id=job_id,
                    status="error",
                    triggered_by=triggered_by,
                    error=f"Unknown job kind: {job.kind}",
                    error_code="unknown_job_kind",
                )
                db.add(run)
                await db.commit()
                observability.job_runs_total.add(1, {"job.kind": job.kind, "status": "error", "triggered_by": triggered_by})
                return

            run = JobRun(job_id=job_id, status="running", triggered_by=triggered_by)
            db.add(run)
            job.last_status = "running"
            await db.commit()
            await db.refresh(run)
            run_id = run.id

            observability.job_queue_wait_seconds.record(queue_wait_s, {"job.kind": job.kind})
            observability.job_in_flight.add(1, {"job.kind": job.kind})
            handler_start = time.perf_counter()

            error_code: str | None = None
            error_stage: str | None = None
            caught_exc: Exception | None = None
            try:
                with _tracer.start_as_current_span(
                    "job.run",
                    attributes={"job.kind": job.kind, "job.id": job.id, "job.triggered_by": triggered_by},
                ):
                    log_excerpt = await spec.handler(db, dict(job.params or {}))
                await db.commit()
                # A handler signals a non-fatal partial result (e.g. "found
                # the site but no address on it") by prefixing its returned
                # message with "WARNING:" - it didn't raise, so it isn't an
                # "error", but silently calling it "success" would hide
                # exactly the kind of gap this scan exists to catch.
                warning_code = parse_warning(log_excerpt)
                run_status = "warning" if warning_code else "success"
                error_code = warning_code
                await _finalize(
                    job_id,
                    run_id,
                    status=run_status,
                    error=None,
                    error_code=error_code,
                    error_stage=None,
                    log_excerpt=log_excerpt,
                    started_at=started_at,
                )
            except Exception as exc:
                await db.rollback()
                run_status = "error"
                caught_exc = exc
                error_code, error_stage = classify_exception(exc)
                await _finalize(
                    job_id,
                    run_id,
                    status=run_status,
                    error=f"{type(exc).__name__}: {exc}",
                    error_code=error_code,
                    error_stage=error_stage,
                    log_excerpt=traceback.format_exc()[-4000:],
                    started_at=started_at,
                )
            finally:
                observability.job_in_flight.add(-1, {"job.kind": job.kind})
                duration_s = time.perf_counter() - handler_start
                observability.job_duration_seconds.record(duration_s, {"job.kind": job.kind, "status": run_status})
                observability.job_runs_total.add(
                    1,
                    {
                        "job.kind": job.kind,
                        "status": run_status,
                        "error_code": error_code or "",
                        # Carried so the dashboard can group failures by where
                        # they happened (fetch/parse/llm/db) from metrics alone,
                        # rather than needing a SQL query against job_runs.
                        # Small fixed set - classify_exception() is the only
                        # thing that sets it.
                        "error_stage": error_stage or "",
                        "triggered_by": triggered_by,
                    },
                )
                log_level = {"success": logging.INFO, "warning": logging.WARNING, "error": logging.ERROR}[run_status]
                logger.log(
                    log_level,
                    "job_finished",
                    extra={
                        "job_id": job.id,
                        "run_id": run_id,
                        "job_kind": job.kind,
                        "status": run_status,
                        "error_code": error_code,
                        "error_stage": error_stage,
                        "duration_ms": round(duration_s * 1000, 1),
                        "queue_wait_ms": round(queue_wait_s * 1000, 1),
                        "triggered_by": triggered_by,
                    },
                    exc_info=caught_exc,
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
