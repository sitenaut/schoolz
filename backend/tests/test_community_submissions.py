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
            files={"file": ("handbook.pdf", b"%PDF-1.4 real bytes here", "application/pdf")},
        )
        submission_id = created.json()["id"]

        admin = await _admin_headers(client)
        res = await client.get(f"/submissions/{submission_id}/file", headers=admin)
        assert res.status_code == 200
        assert res.content == b"%PDF-1.4 real bytes here"
        assert res.headers["content-type"] == "application/pdf"


# --- Who sent it: bot check, rate limit, file type, source record ----------


_JPEG = b"\xff\xd8\xff\xe0 not really a photo"


async def _attempts_for(client: AsyncClient, admin: dict, ip: str) -> list[dict]:
    res = await client.get("/submissions/attempts", headers=admin)
    assert res.status_code == 200, res.text
    return [a for a in res.json() if a["ip"] == ip]


@pytest.mark.anyio
async def test_an_upload_records_where_it_came_from_and_keeps_it_after_deletion():
    ip = f"203.0.113.{uuid.uuid4().int % 250}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/submissions",
            files={"file": ("flyer.jpg", _JPEG, "image/jpeg")},
            data={"submitter_name": "A Parent", "submitter_email": "parent@example.com"},
            headers={
                "Fly-Client-IP": ip,
                "X-Forwarded-For": f"10.9.9.9, {ip}",
                "User-Agent": "TestBrowser/1.0",
                "Accept-Language": "en-US",
                "Referer": "https://schoolz.example/upload",
            },
        )
        assert res.status_code == 201, res.text
        # The sender is never shown what was recorded about them.
        assert res.json()["source"] is None
        sid = res.json()["id"]

        admin = await _admin_headers(client)
        listed = next(r for r in (await client.get("/submissions", headers=admin)).json() if r["id"] == sid)
        source = listed["source"]
        assert source["ip"] == ip
        assert source["forwarded_for"] == f"10.9.9.9, {ip}"
        assert source["user_agent"] == "TestBrowser/1.0"
        assert source["referer"] == "https://schoolz.example/upload"
        assert source["outcome"] == "accepted"
        assert source["file_detected_type"] == "image/jpeg"
        assert len(source["file_sha256"]) == 64

        assert (await client.delete(f"/submissions/{sid}", headers=admin)).status_code == 204
        kept = await _attempts_for(client, admin, ip)
        assert len(kept) == 1
        assert kept[0]["submission_id"] is None
        assert kept[0]["file_sha256"] == source["file_sha256"]
        assert kept[0]["submitter_email"] == "parent@example.com"


@pytest.mark.anyio
async def test_a_file_that_is_not_an_image_or_pdf_is_refused_whatever_it_claims_to_be():
    ip = f"198.51.100.{uuid.uuid4().int % 250}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/submissions",
            files={"file": ("flyer.jpg", b"<html><script>alert(1)</script></html>", "image/jpeg")},
            headers={"Fly-Client-IP": ip},
        )
        assert res.status_code == 400
        admin = await _admin_headers(client)
        attempts = await _attempts_for(client, admin, ip)
        assert [a["outcome"] for a in attempts] == ["bad_file_type"]
        assert attempts[0]["file_declared_type"] == "image/jpeg"
        assert attempts[0]["file_sha256"]


@pytest.mark.anyio
async def test_stored_type_comes_from_the_bytes_not_the_sender():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/submissions", files={"file": ('a"b/../evil.html', _JPEG, "text/html")})
        assert res.status_code == 201, res.text
        assert res.json()["file_content_type"] == "image/jpeg"
        assert res.json()["file_name"] == "evil.html"
        admin = await _admin_headers(client)
        got = await client.get(f"/submissions/{res.json()['id']}/file", headers=admin)
        assert got.headers["content-type"] == "image/jpeg"
        assert got.headers["x-content-type-options"] == "nosniff"


@pytest.mark.anyio
async def test_failed_bot_check_refuses_and_is_recorded(monkeypatch):
    from services import upload_guard

    seen = {}

    async def fail(token, ip):
        seen.update(token=token, ip=ip)
        return False, {"success": False, "error-codes": ["invalid-input-response"]}

    monkeypatch.setattr(upload_guard, "verify_bot_check", fail)
    ip = f"192.0.2.{uuid.uuid4().int % 250}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/submissions",
            files={"file": ("flyer.jpg", _JPEG, "image/jpeg")},
            data={"bot_token": "tok"},
            headers={"Fly-Client-IP": ip},
        )
        assert res.status_code == 400
        assert seen == {"token": "tok", "ip": ip}
        admin = await _admin_headers(client)
        attempts = await _attempts_for(client, admin, ip)
        assert [a["outcome"] for a in attempts] == ["bot_check_failed"]
        assert attempts[0]["bot_check"]["error-codes"] == ["invalid-input-response"]


@pytest.mark.anyio
async def test_bot_check_is_never_skipped_in_prod_without_a_secret(monkeypatch):
    monkeypatch.setenv("APP_ENV", "prod")
    monkeypatch.delenv("TURNSTILE_SECRET_KEY", raising=False)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/submissions", files={"file": ("flyer.jpg", _JPEG, "image/jpeg")})
        assert res.status_code == 503
        # A link stores no file, and the chatbot's submit tool has no browser.
        link = await client.post("/submissions", data={"url": "https://example.com/n"})
        assert link.status_code == 201


@pytest.mark.anyio
async def test_filled_honeypot_is_refused():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post(
            "/submissions", files={"file": ("flyer.jpg", _JPEG, "image/jpeg")}, data={"website": "http://spam.example"}
        )
        assert res.status_code == 400


@pytest.mark.anyio
async def test_one_address_is_cut_off_after_too_many_attempts():
    ip = f"203.0.113.{uuid.uuid4().int % 250}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        for _ in range(10):
            ok = await client.post("/submissions", data={"url": "https://example.com/n"}, headers={"Fly-Client-IP": ip})
            assert ok.status_code == 201, ok.text
        blocked = await client.post("/submissions", data={"url": "https://example.com/n"}, headers={"Fly-Client-IP": ip})
        assert blocked.status_code == 429
        other = await client.post("/submissions", data={"url": "https://example.com/n"}, headers={"Fly-Client-IP": "203.0.113.251"})
        assert other.status_code == 201


@pytest.mark.anyio
async def test_a_link_must_be_a_web_address():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.post("/submissions", data={"url": "javascript:alert(1)"})
        assert res.status_code == 400


@pytest.mark.anyio
async def test_a_submissions_admin_adds_their_own_without_the_challenge_or_the_limit(monkeypatch):
    from services import upload_guard

    async def fail(token, ip):
        return False, {"success": False}

    monkeypatch.setattr(upload_guard, "verify_bot_check", fail)
    ip = f"192.0.2.{uuid.uuid4().int % 250}"
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        for _ in range(12):
            res = await client.post(
                "/submissions", files={"file": ("flyer.jpg", _JPEG, "image/jpeg")}, headers={**admin, "Fly-Client-IP": ip}
            )
            assert res.status_code == 201, res.text
        attempts = await _attempts_for(client, admin, ip)
        assert len(attempts) == 12
        assert attempts[0]["user_email"].startswith("sub_admin_")
        assert attempts[0]["bot_check"] == {"skipped": "staff"}

        # A signed-in visitor with no such permission is still a stranger here.
        tag = uuid.uuid4().hex[:8]
        reg = await client.post(
            "/auth/register", json={"email": f"plain_{tag}@example.com", "username": f"plain_{tag}", "password": "password123"}
        )
        plain = {"Authorization": f"Bearer {reg.json()['access_token']}", "Fly-Client-IP": "192.0.2.253"}
        res = await client.post("/submissions", files={"file": ("flyer.jpg", _JPEG, "image/jpeg")}, headers=plain)
        assert res.status_code == 400
