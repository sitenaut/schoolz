import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from sqlalchemy import func, select

import database
from models import JobRun, ScheduledJob
from scheduler import runner
from scheduler.registry import registry


@pytest.mark.anyio
async def test_a_second_run_of_a_live_job_is_skipped_not_run(monkeypatch):
    """Regression: the session-level advisory lock was tied to a connection the
    session had already given back, so a second run of the same job (create
    with "Run once", then click Run) was never excluded."""
    ran = []

    async def _handler(db, params):
        ran.append(1)
        return "done"

    kind = "test.claim"
    monkeypatch.setattr(runner, "SessionLocal", database.SessionLocal)  # runner imported it by name
    monkeypatch.setitem(registry, kind, type("Spec", (), {"handler": staticmethod(_handler)})())

    async with database.SessionLocal() as db:
        job = ScheduledJob(kind=kind, name="claim test", cron_expr="0 8 * * 1", timezone="America/New_York", params={})
        db.add(job)
        await db.commit()
        db.add(JobRun(job_id=job.id, status="running", triggered_by="manual"))
        await db.commit()
        job_id = job.id

    await runner._execute_locked(job_id, triggered_by="manual")

    assert ran == []
    async with database.SessionLocal() as db:
        statuses = (await db.execute(select(JobRun.status).where(JobRun.job_id == job_id))).scalars().all()
    assert sorted(statuses) == ["running", "skipped"]


@pytest.mark.anyio
async def test_a_stale_running_row_does_not_block_a_new_run(monkeypatch):
    """A crashed run's `running` row must not wedge the job forever."""
    ran = []

    async def _handler(db, params):
        ran.append(1)
        return "done"

    kind = "test.claim"
    monkeypatch.setattr(runner, "SessionLocal", database.SessionLocal)  # runner imported it by name
    monkeypatch.setitem(registry, kind, type("Spec", (), {"handler": staticmethod(_handler)})())

    async with database.SessionLocal() as db:
        job = ScheduledJob(kind=kind, name="claim test 2", cron_expr="0 8 * * 1", timezone="America/New_York", params={})
        db.add(job)
        await db.commit()
        old = JobRun(job_id=job.id, status="running", triggered_by="cron")
        db.add(old)
        await db.commit()
        old.started_at = func.now() - runner.timedelta(minutes=runner.STUCK_RUN_THRESHOLD_MINUTES + 5)
        await db.commit()
        job_id = job.id

    await runner._execute_locked(job_id, triggered_by="manual")

    assert ran == [1]
