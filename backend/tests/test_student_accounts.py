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


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/auth/register",
        json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"},
    )
    assert res.status_code == 201, res.text
    return res.json()["access_token"]


async def _setup(client: AsyncClient):
    """A guardian with one student on their profile."""
    run = uuid.uuid4().hex[:8]
    guardian_email = f"parent_{run}@example.com"
    guardian = await _register(client, guardian_email)
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == guardian_email).values(is_admin=True))
        await db.commit()
    school = await client.post("/schools", json={"name": f"Test High {run}"}, headers=_auth(guardian))
    student = await client.post(
        "/students",
        json={"first_name": "Alex", "last_name": "Rivera", "student_id": f"s-{run}", "school_id": school.json()["id"]},
        headers=_auth(guardian),
    )
    assert student.status_code == 201, student.text
    return run, guardian, student.json()["id"]


@pytest.mark.anyio
async def test_student_account_invite_accept_and_shared_access():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, student_id = await _setup(client)
        kid_email = f"kid_{run}@example.com"

        invite = await client.post(
            f"/students/{student_id}/account-invites", json={"invitee_email": kid_email}, headers=_auth(guardian)
        )
        assert invite.status_code == 201, invite.text
        token = invite.json()["token"]
        assert invite.json()["accept_url"].endswith(f"/student-invites/{token}")

        preview = await client.get(f"/student-account-invites/{token}")
        assert preview.status_code == 200
        assert preview.json()["student_first_name"] == "Alex"
        assert preview.json()["student_last_initial"] == "R"

        kid = await _register(client, kid_email)
        before = await client.get(f"/students/{student_id}/bucket3/schedule", headers=_auth(kid))
        assert before.status_code == 404

        accepted = await client.post(f"/student-account-invites/{token}/accept", headers=_auth(kid))
        assert accepted.status_code == 200, accepted.text

        me = (await client.get("/auth/me", headers=_auth(kid))).json()
        assert me["student_profile_id"] == student_id

        # The student sees the same bucket3 data the guardian does.
        for path in ("schedule", "workitems", "grades", "audit", "student"):
            res = await client.get(f"/students/{student_id}/bucket3/{path}", headers=_auth(kid))
            assert res.status_code == 200, (path, res.text)
        profile = (await client.get(f"/students/{student_id}/bucket3/student", headers=_auth(kid))).json()
        assert profile["viewer_role"] == "student"
        guardian_view = (await client.get(f"/students/{student_id}/bucket3/student", headers=_auth(guardian))).json()
        assert guardian_view["viewer_role"] == "guardian"

        status = (await client.get(f"/students/{student_id}/student-account", headers=_auth(guardian))).json()
        assert status["has_account"] is True
        assert status["account_email"] == kid_email

        # A student is not a guardian: can't invite, can't see the guardian-only status.
        forbidden = await client.post(
            f"/students/{student_id}/account-invites", json={"invitee_email": "x@example.com"}, headers=_auth(kid)
        )
        assert forbidden.status_code == 404

        # The invite is single-use.
        again = await client.post(f"/student-account-invites/{token}/accept", headers=_auth(kid))
        assert again.status_code == 410


@pytest.mark.anyio
async def test_accept_requires_matching_email():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, student_id = await _setup(client)
        invite = await client.post(
            f"/students/{student_id}/account-invites",
            json={"invitee_email": f"kid_{run}@example.com"},
            headers=_auth(guardian),
        )
        stranger = await _register(client, f"stranger_{run}@example.com")
        res = await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(stranger))
        assert res.status_code == 403


@pytest.mark.anyio
async def test_guardian_cannot_become_their_own_student():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, student_id = await _setup(client)
        guardian_email = f"parent_{run}@example.com"
        invite = await client.post(
            f"/students/{student_id}/account-invites", json={"invitee_email": guardian_email}, headers=_auth(guardian)
        )
        res = await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(guardian))
        assert res.status_code == 409


@pytest.mark.anyio
async def test_reinvite_revokes_previous_and_revoke_unlinks():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, student_id = await _setup(client)
        first = await client.post(
            f"/students/{student_id}/account-invites",
            json={"invitee_email": f"typo_{run}@example.com"},
            headers=_auth(guardian),
        )
        second = await client.post(
            f"/students/{student_id}/account-invites",
            json={"invitee_email": f"kid_{run}@example.com"},
            headers=_auth(guardian),
        )
        assert (await client.get(f"/student-account-invites/{first.json()['token']}")).json()["status"] == "revoked"

        kid = await _register(client, f"kid_{run}@example.com")
        accepted = await client.post(f"/student-account-invites/{second.json()['token']}/accept", headers=_auth(kid))
        assert accepted.status_code == 200

        dup = await client.post(
            f"/students/{student_id}/account-invites",
            json={"invitee_email": f"other_{run}@example.com"},
            headers=_auth(guardian),
        )
        assert dup.status_code == 409

        revoked = await client.delete(f"/students/{student_id}/student-account", headers=_auth(guardian))
        assert revoked.status_code == 204
        assert (await client.get("/auth/me", headers=_auth(kid))).json()["student_profile_id"] is None
        lost = await client.get(f"/students/{student_id}/bucket3/schedule", headers=_auth(kid))
        assert lost.status_code == 404


@pytest.mark.anyio
async def test_deleting_student_login_unlinks_student_row():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, student_id = await _setup(client)
        kid_email = f"kid_{run}@example.com"
        invite = await client.post(
            f"/students/{student_id}/account-invites", json={"invitee_email": kid_email}, headers=_auth(guardian)
        )
        kid = await _register(client, kid_email)
        await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(kid))

        deleted = await client.request(
            "DELETE", "/auth/me", json={"confirm": "DELETE", "password": "password123"}, headers=_auth(kid)
        )
        assert deleted.status_code == 204, deleted.text

        status = (await client.get(f"/students/{student_id}/student-account", headers=_auth(guardian))).json()
        assert status["has_account"] is False
        # The student record and the guardian's access are untouched.
        assert (await client.get(f"/students/{student_id}/bucket3/schedule", headers=_auth(guardian))).status_code == 200
