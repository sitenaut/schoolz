import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import UTC

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import ScheduledJob, User


async def _register(client: AsyncClient, tag: str, *, admin: bool) -> dict[str, str]:
    email = f"{tag}_{uuid.uuid4().hex[:8]}@example.com"
    res = await client.post("/auth/register", json={"email": email, "username": f"{tag}_{uuid.uuid4().hex[:8]}", "password": "password123"})
    assert res.status_code == 201, res.text
    if admin:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.anyio
async def test_job_crud_lifecycle_and_target_resolution():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _register(client, "admin", admin=True)

        kinds = await client.get("/scheduled-jobs/kinds", headers=admin)
        assert kinds.status_code == 200
        by_kind = {k["kind"]: k for k in kinds.json()}
        assert "school_info.scan" in by_kind
        assert by_kind["school_info.scan"]["param_schema"]["required"] == ["school_id"]

        school = await client.post("/schools", json={"name": f"Test Elementary {uuid.uuid4().hex[:6]}"}, headers=admin)
        assert school.status_code == 201, school.text
        school_id = school.json()["id"]

        created = await client.post(
            "/scheduled-jobs",
            json={
                "kind": "school_info.scan",
                "name": "Manual info scan",
                "description": "Created from the jobs UI",
                "cron_expr": "0 6 * * *",
                "timezone": "America/New_York",
                "params": {"school_id": school_id},
                "enabled": False,
            },
            headers=admin,
        )
        assert created.status_code == 201, created.text
        job = created.json()
        assert job["target_type"] == "school"
        assert job["target_label"] == school.json()["short_name"] or job["target_label"] == school.json()["name"]
        assert job["enabled"] is False
        assert job["params"] == {"school_id": school_id}

        listed = await client.get("/scheduled-jobs", headers=admin)
        assert any(j["id"] == job["id"] for j in listed.json())

        patched = await client.patch(
            f"/scheduled-jobs/{job['id']}", json={"cron_expr": "0 */12 * * *", "enabled": True, "name": "Renamed"}, headers=admin
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["cron_expr"] == "0 */12 * * *"
        assert patched.json()["name"] == "Renamed"
        assert patched.json()["enabled"] is True

        runs = await client.get(f"/scheduled-jobs/{job['id']}/runs", headers=admin)
        assert runs.status_code == 200 and runs.json() == []

        summary = await client.get("/scheduled-jobs/runs/summary", headers=admin)
        assert summary.status_code == 200
        assert summary.json()["total"] >= 1

        deleted = await client.delete(f"/scheduled-jobs/{job['id']}", headers=admin)
        assert deleted.status_code == 204
        assert (await client.get(f"/scheduled-jobs/{job['id']}", headers=admin)).status_code == 404


@pytest.mark.anyio
async def test_job_create_validation():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _register(client, "admin", admin=True)
        base = {"name": "x", "cron_expr": "0 6 * * *", "timezone": "America/New_York", "params": {}}

        bad_kind = await client.post("/scheduled-jobs", json={**base, "kind": "nope.scan"}, headers=admin)
        assert bad_kind.status_code == 400 and "Unknown job kind" in bad_kind.text

        missing = await client.post("/scheduled-jobs", json={**base, "kind": "school_info.scan"}, headers=admin)
        assert missing.status_code == 400 and "school_id" in missing.text

        bad_cron = await client.post(
            "/scheduled-jobs", json={**base, "kind": "school_info.scan", "params": {"school_id": "x"}, "cron_expr": "not a cron"}, headers=admin
        )
        assert bad_cron.status_code == 400 and "cron" in bad_cron.text.lower()

        bad_tz = await client.post(
            "/scheduled-jobs", json={**base, "kind": "school_info.scan", "params": {"school_id": "x"}, "timezone": "Mars/Olympus"}, headers=admin
        )
        assert bad_tz.status_code == 400 and "timezone" in bad_tz.text.lower()


@pytest.mark.anyio
async def test_jobs_api_is_admin_only():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        guardian = await _register(client, "parent", admin=False)
        for method, path in (("get", "/scheduled-jobs"), ("get", "/scheduled-jobs/kinds"), ("post", "/scheduled-jobs/x/run-now")):
            res = await client.request(method, path, headers=guardian)
            assert res.status_code == 403, f"{method} {path}: {res.status_code}"
        anon = await client.get("/scheduled-jobs")
        assert anon.status_code == 401


@pytest.mark.anyio
async def test_stuck_run_reaper_keys_on_last_progress_not_start():
    """A long job that keeps checkpointing progress (local_events.refresh with
    the Y's slow schedules runs ~50 min) must not be reaped mid-flight; a run
    with no heartbeat for 45 min still is."""
    from datetime import datetime, timedelta

    import database
    from models import JobRun, ScheduledJob
    from scheduler.entrypoint import _REAP_STUCK_RUNS_SQL

    now = datetime.now(UTC)
    async with database.SessionLocal() as db:
        job = ScheduledJob(kind="local_events.refresh", name="reaper test", cron_expr="0 */3 * * *", params={})
        db.add(job)
        await db.flush()
        alive = JobRun(job_id=job.id, status="running", started_at=now - timedelta(minutes=60), last_progress_at=now - timedelta(minutes=2))
        dead = JobRun(job_id=job.id, status="running", started_at=now - timedelta(minutes=60), last_progress_at=now - timedelta(minutes=50))
        silent = JobRun(job_id=job.id, status="running", started_at=now - timedelta(minutes=60))
        db.add_all([alive, dead, silent])
        await db.flush()
        await db.execute(_REAP_STUCK_RUNS_SQL, {"machine_id": None, "process_started_at": now})
        for run in (alive, dead, silent):
            await db.refresh(run)
        assert alive.status == "running"
        assert dead.status == "error" and dead.error_code == "abandoned"
        assert silent.status == "error"  # no heartbeat at all: falls back to started_at


@pytest.mark.anyio
async def test_reaper_finalizes_this_machines_runs_from_a_previous_process_at_once():
    """After a deploy the scheduler's catch-up run was skipped as "already in
    progress" because the killed run still had a fresh heartbeat. A run this
    machine started before this process did is reaped straight away; another
    machine's run, or one this process started, is left alone."""
    from datetime import datetime, timedelta

    import database
    from models import JobRun, ScheduledJob
    from scheduler.entrypoint import _REAP_STUCK_RUNS_SQL

    now = datetime.now(UTC)
    process_started_at = now - timedelta(minutes=1)
    async with database.SessionLocal() as db:
        job = ScheduledJob(kind="prerender.warm", name="orphan reaper test", cron_expr="40 22 * * *", params={})
        db.add(job)
        await db.flush()
        orphan = JobRun(job_id=job.id, status="running", machine_id="m-sched", started_at=now - timedelta(minutes=20), last_progress_at=now - timedelta(minutes=3))
        ours = JobRun(job_id=job.id, status="running", machine_id="m-sched", started_at=now - timedelta(seconds=10))
        elsewhere = JobRun(job_id=job.id, status="running", machine_id="m-api", started_at=now - timedelta(minutes=20), last_progress_at=now - timedelta(minutes=3))
        db.add_all([orphan, ours, elsewhere])
        await db.flush()
        await db.execute(_REAP_STUCK_RUNS_SQL, {"machine_id": "m-sched", "process_started_at": process_started_at})
        for run in (orphan, ours, elsewhere):
            await db.refresh(run)
        assert orphan.status == "error" and orphan.error_code == "abandoned"
        assert ours.status == "running"
        assert elsewhere.status == "running"


@pytest.mark.anyio
async def test_list_jobs_filters_by_last_status_and_enabled():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _register(client, "jobfilter", admin=True)
        tag = uuid.uuid4().hex[:8]
        school = await client.post("/schools", json={"name": f"Filter Elementary {tag}"}, headers=admin)
        assert school.status_code == 201, school.text
        ids = {}
        for label, enabled in (("broken", True), ("broken_off", False), ("fine", True), ("fresh", True)):
            created = await client.post(
                "/scheduled-jobs",
                json={"kind": "school_info.scan", "name": f"{label} {tag}", "cron_expr": "0 6 * * *",
                      "timezone": "America/New_York", "params": {"school_id": school.json()["id"]}, "enabled": enabled},
                headers=admin,
            )
            assert created.status_code == 201, created.text
            ids[label] = created.json()["id"]
        async with database.SessionLocal() as db:
            await db.execute(update(ScheduledJob).where(ScheduledJob.id.in_([ids["broken"], ids["broken_off"]])).values(last_status="error"))
            await db.execute(update(ScheduledJob).where(ScheduledJob.id == ids["fine"]).values(last_status="success"))
            await db.commit()

        async def listed(query: str) -> set[str]:
            res = await client.get(f"/scheduled-jobs?{query}", headers=admin)
            assert res.status_code == 200, res.text
            return {j["id"] for j in res.json()} & set(ids.values())

        assert await listed("last_status=error") == {ids["broken"], ids["broken_off"]}
        assert await listed("last_status=error&enabled=true") == {ids["broken"]}
        assert await listed("last_status=never") == {ids["fresh"]}
        assert await listed("enabled=false") == {ids["broken_off"]}
        assert await listed("kind=school_info.scan") == set(ids.values())


def test_job_sources_say_what_a_scan_reads():
    from types import SimpleNamespace

    from scheduler.sources import job_sources

    district = SimpleNamespace(website_url="https://district.example", ics_feeds=[{"name": "Main", "url": "https://district.example/cal.ics"}])
    school = SimpleNamespace(
        website_url="https://school.example", school_type="elementary", apptegy_org_id=None, staff_directory_url="https://school.example/staff"
    )

    docs = job_sources("documents.scan", school=school, district=district)
    assert {"label": "School website", "value": "https://school.example"} in docs
    assert any(s["value"] == "https://district.example" for s in docs)

    # The roster reads the directory when one is set, not the homepage.
    assert job_sources("staff_roster.scan", school=school, district=district)[0] == {"label": "Staff directory", "value": "https://school.example/staff"}
    assert job_sources("district_calendar.scan", district=district) == [{"label": "Calendar feed: Main", "value": "https://district.example/cal.ics"}]
    assert job_sources("smore.scan", newsletter_url="https://smore.example/n/abc") == [{"label": "Newsletter", "value": "https://smore.example/n/abc"}]
    # Unset field, unknown kind, deleted target: nothing to show, never an error.
    assert job_sources("athletics_calendar.scan", school=SimpleNamespace(athletics_url=None)) == []
    assert job_sources("prerender.warm") == []
    assert job_sources("documents.scan", school=None) == []


@pytest.mark.anyio
async def test_job_out_includes_the_url_it_fetches():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _register(client, "jobsrc", admin=True)
        school = await client.post(
            "/schools", json={"name": f"Source Middle {uuid.uuid4().hex[:6]}", "website_url": "https://sources.example"}, headers=admin
        )
        assert school.status_code == 201, school.text
        jobs = (await client.get("/scheduled-jobs?kind=documents.scan", headers=admin)).json()
        mine = [j for j in jobs if j["params"].get("school_id") == school.json()["id"]]
        assert mine, "setting website_url should have auto-created the documents scan"
        assert {"label": "School website", "value": "https://sources.example"} in mine[0]["sources"]


@pytest.mark.anyio
async def test_run_now_refuses_a_job_that_is_already_running():
    """A Run click while a scan is in flight (e.g. right after creating a
    "Run once" newsletter, which scans immediately) says so, instead of
    queueing a second run."""
    from models import JobRun

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _register(client, "admin", admin=True)
        school = await client.post("/schools", json={"name": f"Test Elementary {uuid.uuid4().hex[:6]}"}, headers=admin)
        created = await client.post(
            "/scheduled-jobs",
            json={
                "kind": "school_info.scan",
                "name": "Busy scan",
                "cron_expr": "0 6 * * *",
                "timezone": "America/New_York",
                "params": {"school_id": school.json()["id"]},
                "enabled": False,
            },
            headers=admin,
        )
        job_id = created.json()["id"]
        async with database.SessionLocal() as db:
            db.add(JobRun(job_id=job_id, status="running", triggered_by="manual"))
            await db.commit()

        res = await client.post(f"/scheduled-jobs/{job_id}/run-now", headers=admin)

        assert res.status_code == 409
        assert "already running" in res.text


@pytest.mark.anyio
async def test_scheduler_heartbeat_is_stamped_and_shown_in_the_summary(monkeypatch):
    """The scheduler-down alert reads this row, and the admin overview shows it."""
    from sqlalchemy import delete

    from models import SchedulerHeartbeat
    from scheduler import entrypoint

    monkeypatch.setattr(entrypoint, "SessionLocal", database.SessionLocal)
    async with database.SessionLocal() as db:
        await db.execute(delete(SchedulerHeartbeat))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _register(client, "admin", admin=True)
        before = await client.get("/scheduled-jobs/runs/summary", headers=admin)
        assert before.json()["scheduler_last_seen_at"] is None

        await entrypoint._beat()
        first = (await client.get("/scheduled-jobs/runs/summary", headers=admin)).json()["scheduler_last_seen_at"]
        await entrypoint._beat()
        second = (await client.get("/scheduled-jobs/runs/summary", headers=admin)).json()["scheduler_last_seen_at"]
    assert first is not None and second > first

    async with database.SessionLocal() as db:
        rows = (await db.execute(select(SchedulerHeartbeat))).scalars().all()
    assert len(rows) == 1 and rows[0].id == "scheduler"
