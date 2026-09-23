import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select, text

import scheduler.jobs  # noqa: F401  (registers all job kinds via decorators)
import telemetry
import observability
from database import SessionLocal, engine
from logging_config import setup_logging
from models import ScheduledJob
from scheduler.runner import build_apscheduler_job

setup_logging()
telemetry.setup_telemetry("schoolz-scheduler")
telemetry.instrument_sqlalchemy_engine(engine)
logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 30
STUCK_RUN_THRESHOLD_MINUTES = 45

_stop_event = asyncio.Event()

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
    WHERE status = 'running' AND started_at < now() - interval '45 minutes'
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
        job_ids = [row[0] for row in (await db.execute(_REAP_STUCK_RUNS_SQL)).all()]
        if job_ids:
            await db.execute(_REAP_STUCK_JOBS_SQL, {"job_ids": job_ids})
            logger.warning("reaped_stuck_runs", extra={"job_ids": job_ids, "count": len(job_ids)})
        await db.commit()


async def _reconcile(aps_scheduler: AsyncIOScheduler) -> None:
    async with SessionLocal() as db:
        jobs = (await db.execute(select(ScheduledJob))).scalars().all()
        seen_ids = set()
        for job in jobs:
            build_apscheduler_job(aps_scheduler, job)
            seen_ids.add(f"job-{job.id}")

        for existing in aps_scheduler.get_jobs():
            if existing.id.startswith("job-") and existing.id not in seen_ids:
                aps_scheduler.remove_job(existing.id)


async def _reconcile_loop(aps_scheduler: AsyncIOScheduler) -> None:
    while not _stop_event.is_set():
        try:
            await _reap_stuck_runs()
        except Exception:
            logger.exception("stuck_run_reap_failed")
        try:
            await _reconcile(aps_scheduler)
            # Heartbeat. Nothing else proves this process is alive: with no
            # jobs due, a healthy scheduler and a dead one emit identical
            # (absent) job metrics, so the "scans stopped running" alert
            # keys off this tick rather than off job activity.
            observability.scheduler_reconciles_total.add(1)
        except Exception:
            logger.exception("scheduler_reconcile_failed")
        try:
            await asyncio.wait_for(_stop_event.wait(), timeout=RECONCILE_INTERVAL_SECONDS)
        except asyncio.TimeoutError:
            pass


def _handle_stop_signal(*_args) -> None:
    _stop_event.set()


async def main() -> None:
    aps_scheduler = AsyncIOScheduler(timezone="UTC")
    aps_scheduler.start()
    logger.info("scheduler_started")

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGTERM, signal.SIGINT):
        loop.add_signal_handler(sig, _handle_stop_signal)

    await _reconcile_loop(aps_scheduler)

    logger.info("scheduler_stopping")
    aps_scheduler.shutdown(wait=False)
    telemetry.shutdown_telemetry()


if __name__ == "__main__":
    asyncio.run(main())
