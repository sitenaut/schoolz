import uuid

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import School, User
from scheduler.jobs import school_info_scan


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"logo_admin_{tag}@example.com"
    res = await client.post("/auth/register", json={"email": email, "username": f"logo_admin_{tag}", "password": "password123"})
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _school(**kw) -> str:
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Logo Test School {tag}", slug=f"logo-test-{tag}", **kw)
        db.add(school)
        await db.commit()
        return school.id


@pytest.fixture
def fake_scan(monkeypatch):
    """The scan with its three network calls stubbed. `state` holds what the
    school's site and the classifier answer; `fetched` records each logo
    the classifier was asked about."""
    state = {"logo_url": "https://cdn.example.org/a.png", "backing": "dark", "fetched": []}

    async def _info(url):
        return {"address": "1 Main St", "main_phone": "(856) 555-0100", "logo_url": state["logo_url"]}

    async def _classify(url):
        state["fetched"].append(url)
        return state["backing"]

    async def _no_location(school):
        return None

    monkeypatch.setattr(school_info_scan, "discover_school_info", _info)
    monkeypatch.setattr(school_info_scan, "classify_logo_url", _classify)
    monkeypatch.setattr(school_info_scan, "ensure_location", _no_location)
    return state


async def _scan(school_id: str) -> School:
    async with database.SessionLocal() as db:
        await school_info_scan.run(db, {"school_id": school_id})
        await db.commit()
        return await db.get(School, school_id)


@pytest.mark.anyio
async def test_scan_classifies_once_then_only_when_the_logo_changes(fake_scan):
    school_id = await _school(website_url="https://school.example.org")

    assert (await _scan(school_id)).logo_backing == "dark"
    # Same logo next run: the stored answer stands, the image isn't refetched.
    fake_scan["backing"] = "light"
    assert (await _scan(school_id)).logo_backing == "dark"
    assert fake_scan["fetched"] == ["https://cdn.example.org/a.png"]

    fake_scan["logo_url"] = "https://cdn.example.org/b.png"
    assert (await _scan(school_id)).logo_backing == "light"


@pytest.mark.anyio
async def test_scan_backfills_a_logo_it_did_not_discover(fake_scan):
    # A school whose logo was set before classification existed (or by hand,
    # where the site scan finds none) still gets classified.
    fake_scan["logo_url"] = None
    school_id = await _school(website_url="https://school.example.org", logo_url="https://cdn.example.org/old.png")
    assert (await _scan(school_id)).logo_backing == "dark"


@pytest.mark.anyio
async def test_failed_fetch_stays_unclassified_and_is_retried(fake_scan):
    school_id = await _school(website_url="https://school.example.org")
    fake_scan["backing"] = None
    assert (await _scan(school_id)).logo_backing is None
    fake_scan["backing"] = "light"
    assert (await _scan(school_id)).logo_backing == "light"
    assert len(fake_scan["fetched"]) == 2


@pytest.mark.anyio
async def test_manual_override_sticks_until_the_logo_changes(fake_scan):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        school_id = await _school(website_url="https://school.example.org")
        await _scan(school_id)

        res = await client.patch(f"/schools/{school_id}", json={"logo_backing": "none"}, headers=admin)
        assert res.status_code == 200 and res.json()["logo_backing"] == "none"
        assert (await _scan(school_id)).logo_backing == "none"

        assert (await client.patch(f"/schools/{school_id}", json={"logo_backing": "pink"}, headers=admin)).status_code == 422

        # A new image drops the override; "" does the same without one.
        res = await client.patch(f"/schools/{school_id}", json={"logo_url": "https://cdn.example.org/c.png"}, headers=admin)
        assert res.json()["logo_backing"] is None
        res = await client.patch(
            f"/schools/{school_id}", json={"logo_url": "https://cdn.example.org/d.png", "logo_backing": "light"}, headers=admin
        )
        assert res.json()["logo_backing"] == "light"
        assert (await client.patch(f"/schools/{school_id}", json={"logo_backing": ""}, headers=admin)).json()["logo_backing"] is None
        # Re-sending the same URL is not a change.
        await client.patch(f"/schools/{school_id}", json={"logo_backing": "dark"}, headers=admin)
        res = await client.patch(f"/schools/{school_id}", json={"logo_url": "https://cdn.example.org/d.png"}, headers=admin)
        assert res.json()["logo_backing"] == "dark"
