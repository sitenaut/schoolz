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


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _register(client: AsyncClient, email: str, username: str) -> str:
    res = await client.post(
        "/auth/register", json={"email": email, "username": username, "password": "password123"}
    )
    assert res.status_code == 201, res.text
    return res.json()["access_token"]


async def _make_admin(email: str) -> None:
    """Schools are admin-managed (centrally, not per-guardian) - these
    tests need to create one to set up their scenario, not test creation
    permissions, so promote the test user directly rather than going
    through self-serve register (which never grants admin)."""
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()


@pytest.mark.anyio
async def test_gary_and_susan_share_only_common_children(monkeypatch, tmp_path):
    # Uses the app's already-configured DB (sqlite/postgres, whatever the
    # test environment provides via DATABASE_URL / DATABASE_HOST etc).
    transport = ASGITransport(app=app)
    run_id = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        susan = await _register(client, f"susan_{run_id}@example.com", _unique("susan"))
        gary = await _register(client, f"gary_{run_id}@example.com", _unique("gary"))
        await _make_admin(f"susan_{run_id}@example.com")

        def auth(token):
            return {"Authorization": f"Bearer {token}"}

        school = await client.post("/schools", json={"name": f"Test Elementary {run_id}"}, headers=auth(susan))
        school_id = school.json()["id"]

        for name, sid in [("Tommy", f"t-{run_id}-1234"), ("Jenny", f"t-{run_id}-5678")]:
            res = await client.post(
                "/students",
                json={"first_name": name, "last_name": "Smith", "student_id": sid, "school_id": school_id},
                headers=auth(susan),
            )
            assert res.status_code == 201, res.text

        for name, sid in [("Tommy", f"t-{run_id}-1234"), ("Jenny", f"t-{run_id}-5678"), ("Alice", f"t-{run_id}-9001")]:
            res = await client.post(
                "/students",
                json={"first_name": name, "last_name": "Smith", "student_id": sid, "school_id": school_id},
                headers=auth(gary),
            )
            assert res.status_code == 201, res.text

        susan_students = (await client.get("/students", headers=auth(susan))).json()
        gary_students = (await client.get("/students", headers=auth(gary))).json()

        assert {s["first_name"] for s in susan_students} == {"Tommy", "Jenny"}
        assert {s["first_name"] for s in gary_students} == {"Tommy", "Jenny", "Alice"}
        assert all(s["guardian_count"] == 2 for s in susan_students)

        tommy_id = next(s["id"] for s in susan_students if s["first_name"] == "Tommy")

        # Gary removing Tommy from his own profile must not affect Susan's.
        res = await client.delete(f"/students/{tommy_id}", headers=auth(gary))
        assert res.status_code == 204

        gary_students_after = (await client.get("/students", headers=auth(gary))).json()
        susan_students_after = (await client.get("/students", headers=auth(susan))).json()
        assert {s["first_name"] for s in gary_students_after} == {"Jenny", "Alice"}
        assert {s["first_name"] for s in susan_students_after} == {"Tommy", "Jenny"}

        notifications = (await client.get("/notifications", headers=auth(susan))).json()
        assert any(n["type"] == "guardian_matched" for n in notifications)


@pytest.mark.anyio
async def test_invite_flow(tmp_path):
    transport = ASGITransport(app=app)
    run_id = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        inviter = await _register(client, f"inviter_{run_id}@example.com", _unique("inviter"))
        await _make_admin(f"inviter_{run_id}@example.com")

        def auth(token):
            return {"Authorization": f"Bearer {token}"}

        school = await client.post("/schools", json={"name": f"Test Middle {run_id}"}, headers=auth(inviter))
        school_id = school.json()["id"]

        res = await client.post(
            "/students",
            json={"first_name": "Nora", "last_name": "Lee", "student_id": f"t-{run_id}-4242", "school_id": school_id},
            headers=auth(inviter),
        )
        student_id = res.json()["id"]

        invite_res = await client.post(
            f"/students/{student_id}/invites",
            json={"invitee_email": f"invitee_{run_id}@example.com"},
            headers=auth(inviter),
        )
        assert invite_res.status_code == 201, invite_res.text
        token = invite_res.json()["token"]

        preview = await client.get(f"/invites/{token}")
        assert preview.status_code == 200
        assert preview.json()["student_first_name"] == "Nora"
        assert preview.json()["student_last_initial"] == "L"

        invitee = await _register(client, f"invitee_{run_id}@example.com", _unique("invitee"))
        accept = await client.post(f"/invites/{token}/accept", headers=auth(invitee))
        assert accept.status_code == 200, accept.text
        assert accept.json()["linked_via"] == "invite_accepted"

        invitee_students = (await client.get("/students", headers=auth(invitee))).json()
        assert {s["first_name"] for s in invitee_students} == {"Nora"}
