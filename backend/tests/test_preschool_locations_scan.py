import uuid

import pytest
from sqlalchemy import select

import database
from models import District, School
from scheduler.jobs import preschool_locations_scan


@pytest.mark.anyio
async def test_a_new_preschool_gets_a_slug_and_a_repeated_name_is_one_school(monkeypatch):
    tag = uuid.uuid4().hex[:8]
    name = f"Little Oaks Preschool {tag}"
    entries = [
        {"name": name, "address": None, "main_phone": None, "website_url": None},
        {"name": name, "address": None, "main_phone": None, "website_url": "https://little-oaks.example"},
    ]

    async def fake_fetch(url, **kwargs):
        return {"html": ""}

    monkeypatch.setattr(preschool_locations_scan.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(preschool_locations_scan, "parse_preschool_locations", lambda html: [dict(e) for e in entries])
    async with database.SessionLocal() as db:
        district = District(name=f"Preschool District {tag}", preschool_locations_url="https://x/preschools")
        db.add(district)
        await db.commit()
        await preschool_locations_scan.run(db, {"district_id": district.id})
        await db.flush()
        schools = (await db.execute(select(School).where(School.district_id == district.id))).scalars().all()
    assert len(schools) == 1 and schools[0].slug and schools[0].website_url == "https://little-oaks.example"
