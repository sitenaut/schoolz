import asyncio
import logging
import signal

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from sqlalchemy import select

import scheduler.jobs  # noqa: F401  (registers all job kinds via decorators)
from database import SessionLocal
from logging_config import setup_logging
from models import ScheduledJob
from scheduler.runner import build_apscheduler_job

setup_logging()
logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 30

_stop_event = asyncio.Event()


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
            await _reconcile(aps_scheduler)
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


if __name__ == "__main__":
    asyncio.run(main())
