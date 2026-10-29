import uuid

import pytest

import database
from models import School
from scheduler.jobs import school_info_scan


@pytest.fixture
def footer(monkeypatch):
    """The scan with its network calls stubbed; `footer` is what the site says."""
    footer = {"address": "132 New Road, Tabernacle, NJ 08088", "main_phone": "609-268-0153", "logo_url": None}

    async def _info(url):
        return dict(footer)

    async def _none(*_):
        return None

    monkeypatch.setattr(school_info_scan, "discover_school_info", _info)
    monkeypatch.setattr(school_info_scan, "classify_logo_url", _none)
    monkeypatch.setattr(school_info_scan, "ensure_location", _none)
    return footer


async def _school(website_url: str, **kw) -> str:
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Info Test School {tag}", slug=f"info-test-{tag}", website_url=website_url, **kw)
        db.add(school)
        await db.commit()
        return school.id


async def _scan(school_id: str) -> tuple[School, str | None]:
    async with database.SessionLocal() as db:
        note = await school_info_scan.run(db, {"school_id": school_id})
        await db.commit()
        return await db.get(School, school_id), note


@pytest.mark.anyio
async def test_own_site_footer_overwrites(footer):
    school_id = await _school(f"https://{uuid.uuid4().hex[:8]}.example.org", address="old", main_phone="old")
    school, _ = await _scan(school_id)
    assert (school.address, school.main_phone) == (footer["address"], footer["main_phone"])


@pytest.mark.anyio
async def test_shared_site_footer_never_overwrites_another_building(footer):
    site = f"https://{uuid.uuid4().hex[:8]}.example.org"
    elementary = await _school(site, address="141 New Road, Tabernacle, NJ 08088", main_phone="609-268-0150")
    await _school(site, address="132 New Road, Tabernacle, NJ 08088", main_phone="609-268-0153")

    school, note = await _scan(elementary)
    assert (school.address, school.main_phone) == ("141 New Road, Tabernacle, NJ 08088", "609-268-0150")
    assert not (note or "").startswith("WARNING")


@pytest.mark.anyio
async def test_shared_site_footer_still_fills_blanks(footer):
    site = f"https://{uuid.uuid4().hex[:8]}.example.org"
    blank = await _school(site)
    await _school(site, address="elsewhere")

    school, _ = await _scan(blank)
    assert (school.address, school.main_phone) == (footer["address"], footer["main_phone"])


@pytest.mark.anyio
async def test_district_footer_on_a_school_page_never_overwrites(footer):
    # Edgewater Park: each school is one page of the district's Smart Sites
    # host, whose footer is the district office.
    footer["shared_footer"] = True
    school_id = await _school(f"https://{uuid.uuid4().hex[:8]}.example.org/magowan", address="405 Cherrix Avenue", main_phone="609-877-1430")
    school, note = await _scan(school_id)
    assert (school.address, school.main_phone) == ("405 Cherrix Avenue", "609-877-1430")
    assert not (note or "").startswith("WARNING")
