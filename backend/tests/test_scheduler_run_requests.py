import asyncio
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from sqlalchemy import select

import database
from models import JobRun, ScheduledJob
from scheduler import runner
from scheduler.registry import registry


async def _job(name: str, **fields) -> str:
    async with database.SessionLocal() as db:
        job = ScheduledJob(kind="test.requested", name=name, cron_expr="0 8 * * 1", timezone="America/New_York", params={}, **fields)
        db.add(job)
        await db.commit()
        return job.id


async def _get(job_id: str) -> ScheduledJob:
    async with database.SessionLocal() as db:
        return (await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))).scalar_one()


@pytest.fixture
def via_scheduler(monkeypatch):
    monkeypatch.setattr(runner, "SessionLocal", database.SessionLocal)  # runner imported it by name
    monkeypatch.setattr(runner, "RUN_NOW_VIA_SCHEDULER", True)
    monkeypatch.setattr(runner, "_requested_in_flight", set())


@pytest.mark.anyio
async def test_run_now_on_fly_only_records_the_request(via_scheduler, monkeypatch):
    """Regression: a run-now executed inside the API process died with no
    error when Fly auto-stopped that machine mid-run."""
    started = []

    async def execute(job_id, **kw):
        started.append(job_id)

    monkeypatch.setattr(runner, "_execute", execute)
    job_id = await _job("requested", last_status="success")
    await runner.run_job_now(job_id)
    await asyncio.sleep(0)

    job = await _get(job_id)
    assert started == [] and job.run_requested_at is not None and job.last_status == "queued"


@pytest.mark.anyio
async def test_a_request_for_a_running_job_keeps_it_showing_running(via_scheduler):
    job_id = await _job("busy", last_status="running")
    await runner.run_job_now(job_id)
    assert (await _get(job_id)).last_status == "running"


@pytest.mark.anyio
async def test_the_scheduler_starts_each_request_once_and_the_run_clears_it(via_scheduler, monkeypatch):
    ran = []

    async def handler(db, params):
        ran.append(1)
        return "done"

    monkeypatch.setitem(registry, "test.requested", type("Spec", (), {"handler": staticmethod(handler)})())
    job_id = await _job("claimed")
    await runner.run_job_now(job_id)

    real_execute = runner._execute
    gate = asyncio.Event()

    async def held(job_id, **kw):  # a run waiting behind the concurrency limit
        await gate.wait()
        await real_execute(job_id, **kw)

    monkeypatch.setattr(runner, "_execute", held)
    assert await runner.claim_requested_runs() == 1
    assert await runner.claim_requested_runs() == 0  # the next tick doesn't start it again
    assert (await _get(job_id)).run_requested_at is not None  # still set while it waits: a restart would pick it up

    gate.set()
    await asyncio.gather(*list(runner._background_tasks))
    job = await _get(job_id)
    assert ran == [1] and job.run_requested_at is None and job.last_status == "success"
    async with database.SessionLocal() as db:
        runs = (await db.execute(select(JobRun.triggered_by).where(JobRun.job_id == job_id))).scalars().all()
    assert runs == ["manual"]


@pytest.mark.anyio
async def test_a_newer_click_survives_the_run_that_answers_an_older_one(via_scheduler, monkeypatch):
    async def handler(db, params):
        return "done"

    monkeypatch.setitem(registry, "test.requested", type("Spec", (), {"handler": staticmethod(handler)})())
    job_id = await _job("clicked twice")
    await runner.run_job_now(job_id)
    first = (await _get(job_id)).run_requested_at
    async with database.SessionLocal() as db:
        job = (await db.execute(select(ScheduledJob).where(ScheduledJob.id == job_id))).scalar_one()
        job.run_requested_at = first + runner.timedelta(seconds=10)
        await db.commit()

    await runner._execute_locked(job_id, triggered_by="manual", requested_at=first)
    assert (await _get(job_id)).run_requested_at == first + runner.timedelta(seconds=10)


@pytest.mark.anyio
async def test_off_fly_run_now_still_runs_in_process(monkeypatch):
    started = []

    async def execute(job_id, **kw):
        started.append((job_id, kw["triggered_by"]))

    monkeypatch.setattr(runner, "RUN_NOW_VIA_SCHEDULER", False)
    monkeypatch.setattr(runner, "_execute", execute)
    await runner.run_job_now("job-1")
    await asyncio.sleep(0)
    assert started == [("job-1", "manual")]
