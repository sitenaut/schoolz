import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import User


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
