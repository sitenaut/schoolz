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


@pytest.mark.anyio
async def test_two_schools_can_each_have_a_pta_newsletter():
    # The job name was "Smore scan: <label>", unique per owner and kind, so
    # the second school's "PTA Newsletter" 500'd.
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _admin_headers(client)
        tag = uuid.uuid4().hex[:6]
        north = (await client.post("/schools", json={"name": f"North Elementary {tag}"}, headers=admin)).json()
        south = (await client.post("/schools", json={"name": f"South Elementary {tag}"}, headers=admin)).json()
        names = []
        for school in (north, south, south):
            url = f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}"
            created = await client.post("/smore-newsletters", json={"url": url, "label": "PTA Newsletter", "school_id": school["id"]}, headers=admin)
            assert created.status_code == 201, created.text
            names.append(created.json()["scheduled_job"]["name"])
    assert names[:2] == [f"Smore scan: PTA Newsletter - North Elementary {tag}", f"Smore scan: PTA Newsletter - South Elementary {tag}"]
    assert names[2] == f"Smore scan: {url}"  # the same label twice at one school falls back to the URL


@pytest.mark.anyio
async def test_moving_a_newsletter_to_its_whole_district_clears_the_school():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _admin_headers(client)
        district = (await client.post("/districts", json={"name": f"Test District {uuid.uuid4().hex[:6]}"}, headers=admin)).json()
        school = (await client.post("/schools", json={"name": f"Test Elementary {uuid.uuid4().hex[:6]}", "district_id": district["id"]}, headers=admin)).json()
        created = await client.post("/smore-newsletters", json={"url": f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", "school_id": school["id"]}, headers=admin)
        nid = created.json()["id"]

        # What the edit form sends: null for the target it didn't pick.
        moved = await client.patch(f"/smore-newsletters/{nid}", json={"school_id": None, "district_id": district["id"]}, headers=admin)
        assert moved.status_code == 200, moved.text
        assert (moved.json()["school_id"], moved.json()["district_id"]) == (None, district["id"])
        # Leaving a field out still leaves it alone.
        relabelled = await client.patch(f"/smore-newsletters/{nid}", json={"label": "Weekly"}, headers=admin)
        assert relabelled.json()["district_id"] == district["id"]

        bad = await client.patch(f"/smore-newsletters/{nid}", json={"school_id": "no-such-school"}, headers=admin)
        assert bad.status_code == 422
        cleared = await client.patch(f"/smore-newsletters/{nid}", json={"district_id": ""}, headers=admin)
        assert cleared.json()["district_id"] is None


@pytest.mark.anyio
async def test_a_school_with_an_unknown_district_is_a_422_and_empty_clears():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _admin_headers(client)
        district = (await client.post("/districts", json={"name": f"Test District {uuid.uuid4().hex[:6]}"}, headers=admin)).json()
        assert (await client.post("/schools", json={"name": "Test Nowhere", "district_id": "no-such-district"}, headers=admin)).status_code == 422
        school = (await client.post("/schools", json={"name": f"Test Elementary {uuid.uuid4().hex[:6]}", "district_id": district["id"]}, headers=admin)).json()
        assert (await client.patch(f"/schools/{school['id']}", json={"district_id": "no-such-district"}, headers=admin)).status_code == 422
        cleared = await client.patch(f"/schools/{school['id']}", json={"district_id": ""}, headers=admin)
        assert cleared.status_code == 200 and cleared.json()["district_id"] is None
