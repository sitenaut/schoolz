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
from scheduler.cron import smore_scan_cron


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"nl_admin_{tag}@example.com"
    res = await client.post("/auth/register", json={"email": email, "username": f"nl_admin_{tag}", "password": "password123"})
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


@pytest.mark.anyio
async def test_district_wide_newsletter_has_no_school_and_resolves_district_name():
    # Real case: Cherry Hill's own "CHPS Weekly" - a district-wide
    # newsletter with no single school to attach to.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)

        district = await client.post("/districts", json={"name": f"Test District {uuid.uuid4().hex[:6]}"}, headers=admin)
        assert district.status_code == 201, district.text
        district_id = district.json()["id"]

        created = await client.post(
            "/smore-newsletters",
            json={"url": f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", "label": "Test Weekly", "district_id": district_id},
            headers=admin,
        )
        assert created.status_code == 201, created.text
        body = created.json()
        assert body["school_id"] is None
        assert body["district_id"] == district_id
        assert body["district_name"] == district.json()["name"]
        # Monday 8 AM like every Smore scan, on the minute its id hashes to.
        assert body["scheduled_job"]["cron_expr"] == smore_scan_cron(body["id"])

        listed = await client.get("/smore-newsletters")
        assert any(n["id"] == body["id"] and n["district_name"] == district.json()["name"] for n in listed.json())


@pytest.mark.anyio
async def test_update_can_move_a_newsletter_from_one_school_to_another():
    # Real case: a school's Smore URL changes to a new one each issue
    # (Bret Harte, Cherry Hill East both did this 2026-09-11) - the admin
    # tracks the new URL and points it at the same school.
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)

        school = await client.post("/schools", json={"name": f"Test Elementary {uuid.uuid4().hex[:6]}"}, headers=admin)
        assert school.status_code == 201, school.text
        school_id = school.json()["id"]

        created = await client.post(
            "/smore-newsletters",
            json={"url": f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", "school_id": school_id},
            headers=admin,
        )
        assert created.status_code == 201
        assert created.json()["school_name"] == school.json()["name"]

        # Old URL retired, new issue tracked separately under the same school.
        new_one = await client.post(
            "/smore-newsletters",
            json={"url": f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", "school_id": school_id, "label": "New issue"},
            headers=admin,
        )
        assert new_one.status_code == 201
        assert new_one.json()["school_id"] == school_id


@pytest.mark.anyio
async def test_duplicate_url_rejected():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        url = f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}"
        first = await client.post("/smore-newsletters", json={"url": url}, headers=admin)
        assert first.status_code == 201
        second = await client.post("/smore-newsletters", json={"url": url}, headers=admin)
        assert second.status_code == 409


@pytest.mark.anyio
async def test_reextract_can_be_narrowed_to_one_block(monkeypatch):
    from models import SmoreBlock
    from services import content_extractor

    seen: list[list[str]] = []

    async def fake_extract(db, newsletter, blocks, job_kind="smore.scan"):
        seen.append([b.id for b in blocks])
        return "ok"

    monkeypatch.setattr(content_extractor, "extract_from_newsletter", fake_extract)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        nl = (await client.post("/smore-newsletters", json={"url": f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}"}, headers=admin)).json()
        async with database.SessionLocal() as db:
            blocks = [SmoreBlock(newsletter_id=nl["id"], position=n, block_type="text", content_hash=uuid.uuid4().hex, text_content=f"b{n}") for n in range(3)]
            db.add_all(blocks)
            await db.commit()
            ids = [b.id for b in blocks]

        assert (await client.post(f"/smore-newsletters/{nl['id']}/reextract-all?block_id={ids[1]}", headers=admin)).status_code == 200
        assert (await client.post(f"/smore-newsletters/{nl['id']}/reextract-all", headers=admin)).status_code == 200
        assert seen == [[ids[1]], ids]
        assert (await client.post(f"/smore-newsletters/{nl['id']}/reextract-all?block_id={uuid.uuid4()}", headers=admin)).status_code == 404
