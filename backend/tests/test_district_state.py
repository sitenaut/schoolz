import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

import database
from main import app
from models import District, ScheduledJob, School, User


def _school(slug: str, name: str, district: str, state: str | None = None) -> dict:
    nulls = {k: None for k in (
        "address", "main_phone", "absence_method", "absence_phone", "absence_portal_name", "absence_portal_url",
        "absence_instructions", "start_time", "end_time", "early_dismissal_time", "delayed_opening_time",
        "athletics_url", "logo_url", "bell_periods", "sacc",
    )}
    out = {"slug": slug, "name": name, "short_name": name, "district_name": district, "school_type": "elementary",
           "absence_emails": [], "website_url": "https://example.org", **nulls}
    if state:
        out["district_state"] = state
    return out


def _district(name: str, state: str | None = None) -> dict:
    nulls = {k: None for k in ("marking_period_url", "preschool_locations_url", "preschool_team_url", "hs_rotation_url", "transportation_url")}
    out = {"name": name, "website_url": "https://example.org", "food_services_menu_url": "https://example.org/menus", "ics_feeds": [], **nulls}
    if state:
        out["state"] = state
    return out


async def _admin(client: AsyncClient) -> dict:
    run_id = uuid.uuid4().hex[:8]
    email = f"admin_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"admin_{run_id}", "password": "password123"})
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"authorization": f"Bearer {reg.json()['access_token']}"}


@pytest.mark.anyio
async def test_same_district_name_in_two_states_is_two_districts():
    """"Washington Township School District" exists in several New Jersey counties
    and in other states, so a name alone cannot be a district's identity."""
    tag = uuid.uuid4().hex[:8]
    name = f"Washington Township {tag}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)

        nj = await client.post("/admin/config/import", headers=headers, json={
            "exported_at": "2026-01-01T00:00:00Z", "source": "t", "districts": [_district(name)],
            "schools": [_school(f"wt-nj-{tag}", f"Lincoln School {tag}", name)], "smore_newsletters": []})
        assert nj.status_code == 200, nj.text
        assert nj.json()["districts_created"] == 1

        # Same name, Pennsylvania: a new district, not an update of the New Jersey one.
        pa = await client.post("/admin/config/import", headers=headers, json={
            "exported_at": "2026-01-01T00:00:00Z", "source": "t", "districts": [_district(name, "PA")],
            "schools": [_school(f"wt-pa-{tag}", f"Lincoln School {tag}", name)], "smore_newsletters": []})
        assert pa.status_code == 200, pa.text
        assert (pa.json()["districts_created"], pa.json()["districts_updated"], pa.json()["schools_created"]) == (1, 0, 1)

        async with database.SessionLocal() as db:
            districts = {d.state: d for d in (await db.execute(select(District).where(District.name == name))).scalars().all()}
            assert set(districts) == {"NJ", "PA"}
            for state, slug in (("NJ", f"wt-nj-{tag}"), ("PA", f"wt-pa-{tag}")):
                school = (await db.execute(select(School).where(School.slug == slug))).scalar_one()
                assert school.district_id == districts[state].id  # each school landed in its own state's district

            # Each state's lunch job is named apart (the same names would collide); New Jersey keeps its bare name.
            names = (await db.execute(select(ScheduledJob.name).where(ScheduledJob.kind == "lunch_menu.scan", ScheduledJob.name.like(f"%{name}%")))).scalars().all()
            assert sorted(names) == [f"Lunch menu scan: {name}", f"Lunch menu scan: {name} (PA)"]


@pytest.mark.anyio
async def test_a_school_names_its_state_when_the_district_is_not_in_the_file():
    tag = uuid.uuid4().hex[:8]
    name = f"Lincoln District {tag}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        for state in ("NJ", "DE"):
            r = await client.post("/admin/config/import", headers=headers, json={
                "exported_at": "2026-01-01T00:00:00Z", "source": "t", "districts": [_district(name, state)], "schools": [], "smore_newsletters": []})
            assert r.status_code == 200, r.text
        # Neither district is in this file, so the school has to say which one.
        r = await client.post("/admin/config/import", headers=headers, json={
            "exported_at": "2026-01-01T00:00:00Z", "source": "t", "districts": [],
            "schools": [_school(f"lincoln-de-{tag}", f"Lincoln School {tag}", name, "DE")], "smore_newsletters": []})
        assert r.status_code == 200, r.text
        async with database.SessionLocal() as db:
            school = (await db.execute(select(School).where(School.slug == f"lincoln-de-{tag}"))).scalar_one()
            district = (await db.execute(select(District).where(District.id == school.district_id))).scalar_one()
            assert (district.state, district.name) == ("DE", name)


@pytest.mark.anyio
async def test_creating_a_district_is_unique_per_state_and_exports_carry_the_state():
    tag = uuid.uuid4().hex[:8]
    name = f"Create District {tag}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        assert (await client.post("/districts", headers=headers, json={"name": name})).status_code == 201  # NJ by default
        assert (await client.post("/districts", headers=headers, json={"name": name})).status_code == 409
        other = await client.post("/districts", headers=headers, json={"name": name, "state": "PA"})
        assert other.status_code == 201 and other.json()["state"] == "PA"
        assert (await client.post("/districts", headers=headers, json={"name": name, "state": "pennsylvania"})).status_code == 422

        export = (await client.get("/admin/config/export", headers=headers)).json()
        assert {d["state"] for d in export["districts"] if d["name"] == name} == {"NJ", "PA"}


@pytest.mark.anyio
async def test_listing_districts_loads_every_districts_jobs_in_one_query(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    job_queries = []
    real_execute = AsyncSession.execute

    async def counting(self, statement, *args, **kwargs):
        if ScheduledJob.__table__ in getattr(statement, "get_final_froms", lambda: [])():
            job_queries.append(statement)
        return await real_execute(self, statement, *args, **kwargs)

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        made = {}
        for n in range(3):
            r = await client.post("/districts", headers=headers, json=_district(f"Jobs District {tag} {n}"))
            assert r.status_code == 201, r.text
            made[r.json()["id"]] = r.json()["scheduled_job"]["id"]
        monkeypatch.setattr(AsyncSession, "execute", counting)
        listed = {d["id"]: d for d in (await client.get("/districts")).json()}

    assert {district_id: listed[district_id]["scheduled_job"]["id"] for district_id in made} == made
    assert len(job_queries) == 1
