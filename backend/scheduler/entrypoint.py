import asyncio
import logging
import os
import signal
from datetime import UTC, datetime

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text
from sqlalchemy.dialects.postgresql import insert

import observability
import scheduler.jobs  # noqa: F401  (registers all job kinds via decorators)
import scraper_client
import telemetry
from database import SessionLocal, engine
from logging_config import setup_logging
from models import ScheduledJob, SchedulerHeartbeat
from scheduler.runner import (
    build_apscheduler_job,
    claim_requested_runs,
    forget_apscheduler_job,
    queue_first_runs,
    queue_missed_runs,
)
from settings import check_settings

setup_logging()
telemetry.setup_telemetry("schoolz-scheduler")
telemetry.instrument_sqlalchemy_engine(engine)
logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 30
# How soon a run-now (runner.run_job_now) starts; one cheap SELECT per tick.
REQUESTED_RUNS_INTERVAL_SECONDS = 5
STUCK_RUN_THRESHOLD_MINUTES = 45

_stop_event = asyncio.Event()
# Set after the first reap, so a requested run never meets the dead
# previous process's 'running' row and gets recorded skipped.
_first_reap_done = asyncio.Event()

# Runs this machine started before this process did belong to a process that
# is gone: the scheduler machine runs nothing else. See _REAP_STUCK_RUNS_SQL.
_MACHINE_ID = os.getenv("FLY_MACHINE_ID")
_PROCESS_STARTED_AT = datetime.now(UTC)

_REAP_STUCK_RUNS_SQL = text(
    """
    UPDATE job_runs SET
        status = 'error',
        error_code = 'abandoned',
        error_stage = 'runtime',
        error = CASE
            WHEN log_excerpt IS NOT NULL THEN
                'process exited mid-run (OOM kill, deploy, or crash) - partial progress was ' ||
                'checkpointed before it died, see log_excerpt (last update ' ||
                COALESCE(to_char(last_progress_at, 'YYYY-MM-DD HH24:MI:SS UTC'), 'unknown') || ')'
            ELSE
                'process exited mid-run (OOM kill, deploy, or crash) - no progress checkpoint ' ||
                'was captured; check Grafana for machine_id/trace_id and started_at on this run'
        END,
        finished_at = now()
    -- Judged by the last progress heartbeat, not the start: a job that
    -- reports progress (local_events.refresh checkpoints after every source)
    -- can legitimately run past 45 minutes - with the Y's schedules rendered
    -- on prod's 1GB scraper it takes ~50 - and keying on started_at marked
    -- live runs "abandoned" mid-flight. Jobs that never report progress
    -- fall back to started_at, as before.
    --
    -- A run this machine started before this process did is reaped at once:
    -- its process is gone (a deploy restarts the scheduler), and waiting out
    -- the 45 minutes kept it looking live, so the catch-up run queued at
    -- startup was recorded "already in progress" and skipped. Two deploys
    -- that way lost prerender.warm's whole night. machine_id is NULL off Fly,
    -- where this clause never matches.
    WHERE status = 'running' AND (
        COALESCE(last_progress_at, started_at) < now() - interval '45 minutes'
        OR (machine_id = :machine_id AND started_at < :process_started_at)
    )
    RETURNING job_id
    """
)

_REAP_STUCK_JOBS_SQL = text(
    """
    UPDATE scheduled_jobs SET
        last_status = 'error',
        last_error_code = 'abandoned',
        last_error = 'process exited mid-run (OOM kill, deploy, or crash)'
    WHERE id = ANY(:job_ids) AND last_status = 'running'
    """
)


async def _reap_stuck_runs() -> None:
    """A run left in status='running' means the process that owned it died
    mid-handler (OOM kill, deploy, crash) - the advisory lock is released
    automatically when its connection drops, but the row itself never gets
    finalized. Without this, an abandoned run stays 'running' forever and
    never counts as the failure it actually was."""
    async with SessionLocal() as db:
        params = {"machine_id": _MACHINE_ID, "process_started_at": _PROCESS_STARTED_AT}
        job_ids = [row[0] for row in (await db.execute(_REAP_STUCK_RUNS_SQL, params)).all()]
        if job_ids:
            await db.execute(_REAP_STUCK_JOBS_SQL, {"job_ids": job_ids})
            logger.warning("reaped_stuck_runs", extra={"job_ids": job_ids, "count": len(job_ids)})
        await db.commit()


async def _reconcile(aps_scheduler: AsyncIOScheduler) -> None:
    async with SessionLocal() as db:
        jobs = (await db.execute(select(ScheduledJob))).scalars().all()
        seen_ids = set()
        for job in jobs:
            seen_ids.add(f"job-{job.id}")
            try:
                build_apscheduler_job(aps_scheduler, job)
            except ValueError:
                # One unschedulable cron (scheduler/cron.py:cron_problem) must
                # not stop every job after it from being scheduled.
                logger.exception("job_cron_unschedulable", extra={"job_id": job.id, "cron_expr": job.cron_expr})

        for existing in aps_scheduler.get_jobs():
            if existing.id.startswith("job-") and existing.id not in seen_ids:
                aps_scheduler.remove_job(existing.id)
                forget_apscheduler_job(existing.id)


async def _beat() -> None:
    """Stamps the scheduler_heartbeats row the scheduler-down alert reads."""
    now = datetime.now(UTC)
    row = {"id": "scheduler", "machine_id": _MACHINE_ID, "started_at": _PROCESS_STARTED_AT, "last_seen_at": now}
    async with SessionLocal() as db:
        await db.execute(
            insert(SchedulerHeartbeat).values(**row).on_conflict_do_update(
                index_elements=[SchedulerHeartbeat.id],
                set_={"machine_id": _MACHINE_ID, "started_at": _PROCESS_STARTED_AT, "last_seen_at": now},
            )
        )
        await db.commit()


async def _reconcile_loop(aps_scheduler: AsyncIOScheduler) -> None:
    caught_up = False
    while not _stop_event.is_set():
        try:
            await _reap_stuck_runs()
        except Exception:
            logger.exception("stuck_run_reap_failed")
        _first_reap_done.set()
        try:
            await _reconcile(aps_scheduler)
            # Heartbeat. Nothing else proves this process is alive: with no
            # jobs due, a healthy scheduler and a dead one emit identical
            # (absent) job metrics. The alert reads the row (_beat), which
            # doesn't depend on telemetry export; the counter feeds dashboards.
            await _beat()
            observability.scheduler_reconciles_total.add(1)
        except Exception:
            logger.exception("scheduler_reconcile_failed")
        if not caught_up:
            # Once per process, after the first reap so a run the previous
            # process died in is already finalized. See missed_fire_time().
            caught_up = True
            try:
                count = await queue_missed_runs()
                logger.info("queued_catch_up_runs", extra={"count": count})
            except Exception:
                logger.exception("catch_up_failed")
        try:
            count = await queue_first_runs()
            if count:
                logger.info("queued_first_runs", extra={"count": count})
        except Exception:
            logger.exception("first_runs_failed")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=RECONCILE_INTERVAL_SECONDS)
        except TimeoutError:
            pass


async def _requested_runs_loop() -> None:
    await _first_reap_done.wait()
    while not _stop_event.is_set():
        try:
            count = await claim_requested_runs()
            if count:
                logger.info("started_requested_runs", extra={"count": count})
        except Exception:
            logger.exception("requested_runs_failed")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=REQUESTED_RUNS_INTERVAL_SECONDS)
        except TimeoutError:
            pass


SCRAPER_HEALTH_INTERVAL_SECONDS = 300


async def _scraper_health_loop() -> None:
    """Whether each scraper is up, measured from here every 5 minutes, so
    an idle scraper that died is noticed before the next scan needs it."""
    while not _stop_event.is_set():
        try:
            for role, healthy in (await scraper_client.check_health()).items():
                observability.scraper_healthy.set(1 if healthy else 0, {"scraper": role})
                if not healthy:
                    logger.warning("scraper_unhealthy", extra={"scraper": role})
        except Exception:
            logger.exception("scraper_health_check_failed")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=SCRAPER_HEALTH_INTERVAL_SECONDS)
        except TimeoutError:
            pass


def _handle_stop_signal(*_args) -> None:
    _stop_event.set()


async def main() -> None:
    check_settings("scheduler")
    aps_scheduler = AsyncIOScheduler(timezone="UTC")
    aps_scheduler.start()
    logger.info("scheduler_started")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_stop_signal)

    await asyncio.gather(_reconcile_loop(aps_scheduler), _requested_runs_loop(), _scraper_health_loop())

    logger.info("scheduler_stopping")
    aps_scheduler.shutdown(wait=False)
    telemetry.shutdown_telemetry()


if __name__ == "__main__":
    asyncio.run(main())
