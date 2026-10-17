import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app


async def _register(client: AsyncClient) -> tuple[str, str, dict[str, str]]:
    tag = uuid.uuid4().hex[:8]
    email, username = f"acct_{tag}@example.com", f"acct_{tag}"
    res = await client.post("/auth/register", json={"email": email, "username": username, "password": "password123"})
    assert res.status_code == 201, res.text
    return email, username, {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _login(client: AsyncClient, ident: str, password: str) -> int:
    return (await client.post("/auth/login", json={"username_or_email": ident, "password": password})).status_code


@pytest.mark.anyio
async def test_me_reports_sign_in_method_and_username_update():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, username, headers = await _register(client)
        me = await client.get("/auth/me", headers=headers)
        assert me.json()["sign_in_method"] == "password"
        assert me.json()["created_at"]

        new_name = f"{username}_renamed"
        res = await client.patch("/auth/me", json={"username": new_name}, headers=headers)
        assert res.status_code == 200 and res.json()["username"] == new_name

        _, other_name, other_headers = await _register(client)
        clash = await client.patch("/auth/me", json={"username": new_name}, headers=other_headers)
        assert clash.status_code == 409
        assert other_name  # unchanged account still fine


@pytest.mark.anyio
async def test_change_password_requires_current_and_takes_effect():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, _, headers = await _register(client)

        wrong = await client.post("/auth/change-password", json={"current_password": "nope", "new_password": "newpassword1"}, headers=headers)
        assert wrong.status_code == 400

        ok = await client.post("/auth/change-password", json={"current_password": "password123", "new_password": "newpassword1"}, headers=headers)
        assert ok.status_code == 204
        assert await _login(client, email, "password123") == 401
        assert await _login(client, email, "newpassword1") == 200


@pytest.mark.anyio
async def test_forgot_and_reset_password_flow():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, _, _ = await _register(client)

        unknown = await client.post("/auth/forgot-password", json={"email": "nobody@example.com"})
        assert unknown.status_code == 200 and unknown.json()["reset_token"] is None

        res = await client.post("/auth/forgot-password", json={"email": email})
        token = res.json()["reset_token"]
        assert token

        bad = await client.post("/auth/reset-password", json={"token": "bogus", "new_password": "resetpass99"})
        assert bad.status_code == 400

        good = await client.post("/auth/reset-password", json={"token": token, "new_password": "resetpass99"})
        assert good.status_code == 200 and good.json()["access_token"]
        assert await _login(client, email, "resetpass99") == 200

        # One-shot: the same token can't be replayed.
        replay = await client.post("/auth/reset-password", json={"token": token, "new_password": "another999"})
        assert replay.status_code == 400


@pytest.mark.anyio
async def test_delete_account_requires_confirmation_and_password():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email, _, headers = await _register(client)

        no_confirm = await client.request("DELETE", "/auth/me", json={"confirm": "delete", "password": "password123"}, headers=headers)
        assert no_confirm.status_code == 400

        wrong_pw = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "wrong"}, headers=headers)
        assert wrong_pw.status_code == 400

        gone = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "password123"}, headers=headers)
        assert gone.status_code == 204
        assert await _login(client, email, "password123") == 401
        assert (await client.get("/auth/me", headers=headers)).status_code == 401


@pytest.mark.anyio
async def test_supabase_autoprovision_username_collision():
    from auth import _get_or_create_supabase_user
    from database import SessionLocal

    async with SessionLocal() as db:
        tag = uuid.uuid4().hex[:6]
        claims1 = {"sub": f"sub_1_{tag}", "email": f"collision_{tag}@example.com"}
        claims2 = {"sub": f"sub_2_{tag}", "email": f"collision_{tag}@otherdomain.com"}

        user1 = await _get_or_create_supabase_user(db, claims1)
        assert user1.username == f"collision_{tag}"

        user2 = await _get_or_create_supabase_user(db, claims2)
        assert user2.username == f"collision_{tag}_2"
        assert user2.id != user1.id


def test_mask_email():
    from auth import mask_email

    assert mask_email("student@chclc.org") == "*****@chclc.org"
    assert mask_email("m@example.com") == "*****@example.com"
    assert mask_email("ALEX.RIVERA@SCHOOL.EDU") == "*****@school.edu"
    assert mask_email(None) is None
    assert mask_email("") == ""
    assert mask_email("plain-string") == "plain-string"
    assert mask_email("@domain.com") == "*****@domain.com"




@pytest.mark.anyio
async def test_delete_account_with_published_captures():
    """Backpack Capture imports name their guardian (owner_user_id, NOT NULL):
    deleting that guardian's account removes their own capture archive, and
    the child's record stays for the other guardians."""
    from datetime import UTC, datetime

    from sqlalchemy import select

    import database
    from models import Bucket3Capture, District, School, Student

    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Capture District {run}")
        db.add(district)
        await db.flush()
        school = School(name=f"Capture Elementary {run}", slug=f"capture-elem-{run}", school_type="elementary", district_id=district.id)
        db.add(school)
        await db.commit()
        school_id = school.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _, _, headers = await _register(client)
        _, _, other = await _register(client)
        kid = {"first_name": "Cap", "last_name": "Ture", "student_id": f"c-{run}", "school_id": school_id}
        student_id = (await client.post("/students", json=kid, headers=headers)).json()["id"]
        assert (await client.post("/students", json=kid, headers=other)).status_code == 201
        me = (await client.get("/auth/me", headers=headers)).json()
        async with database.SessionLocal() as db:
            db.add(
                Bucket3Capture(
                    owner_user_id=me["id"],
                    student_id=student_id,
                    adapter="genesis",
                    source_url="https://example.com/genesis",
                    captured_at=datetime.now(UTC),
                    status="imported",
                    char_count=4,
                    content_hash="x" * 64,
                    reduced_text="test",
                )
            )
            await db.commit()

        gone = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "password123"}, headers=headers)
        assert gone.status_code == 204, gone.text
        async with database.SessionLocal() as db:
            assert (await db.execute(select(Bucket3Capture).where(Bucket3Capture.owner_user_id == me["id"]))).first() is None
            assert await db.get(Student, student_id) is not None
