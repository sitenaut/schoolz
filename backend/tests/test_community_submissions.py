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


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"sub_admin_{tag}@example.com"
    res = await client.post("/auth/register", json={"email": email, "username": f"sub_admin_{tag}", "password": "password123"})
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.anyio
async def test_anonymous_can_submit_a_link_with_no_auth():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/submissions",
            data={
                "url": "https://app.smore.com/n/some-flyer",
                "description": "This is our PTA's fall flyer, please pull out the dates",
                "submitter_name": "A Parent",
            },
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["kind"] == "link"
        assert body["status"] == "pending"
        assert body["url"] == "https://app.smore.com/n/some-flyer"


@pytest.mark.anyio
async def test_anonymous_can_upload_a_file():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/submissions",
            files={"file": ("flyer.pdf", b"%PDF-1.4 fake pdf bytes", "application/pdf")},
            data={"description": "Field trip permission slip"},
        )
        assert res.status_code == 201, res.text
        body = res.json()
        assert body["kind"] == "file"
        assert body["file_name"] == "flyer.pdf"
        assert body["file_size"] == len(b"%PDF-1.4 fake pdf bytes")


@pytest.mark.anyio
async def test_submission_requires_either_url_or_file_not_neither_or_both():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        neither = await client.post("/submissions", data={"description": "just a note"})
        assert neither.status_code == 400

        both = await client.post(
            "/submissions",
            data={"url": "https://example.com/x"},
            files={"file": ("a.pdf", b"data", "application/pdf")},
        )
        assert both.status_code == 400


@pytest.mark.anyio
async def test_only_admin_can_list_or_review_submissions():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post("/submissions", data={"url": "https://example.com/newsletter"})
        submission_id = created.json()["id"]

        anon_list = await client.get("/submissions")
        assert anon_list.status_code == 401

        admin = await _admin_headers(client)
        admin_list = await client.get("/submissions", headers=admin)
        assert admin_list.status_code == 200
        assert any(s["id"] == submission_id for s in admin_list.json())

        approved = await client.patch(
            f"/submissions/{submission_id}",
            json={"status": "approved", "admin_notes": "Added as Beck's Smore newsletter"},
            headers=admin,
        )
        assert approved.status_code == 200
        assert approved.json()["status"] == "approved"
        assert approved.json()["admin_notes"] == "Added as Beck's Smore newsletter"


@pytest.mark.anyio
async def test_admin_can_download_the_uploaded_file_back():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        created = await client.post(
            "/submissions",
            files={"file": ("handbook.pdf", b"real bytes here", "application/pdf")},
        )
        submission_id = created.json()["id"]

        admin = await _admin_headers(client)
        res = await client.get(f"/submissions/{submission_id}/file", headers=admin)
        assert res.status_code == 200
        assert res.content == b"real bytes here"
        assert res.headers["content-type"] == "application/pdf"
