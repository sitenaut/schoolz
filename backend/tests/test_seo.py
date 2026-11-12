import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import District, School, SchoolContentItem

_WEB_URL = os.getenv("PUBLIC_WEB_URL", "http://localhost:5173").rstrip("/")


@pytest.mark.anyio
async def test_sitemap_lists_static_routes():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert res.status_code == 200
    assert res.headers["content-type"].startswith("application/xml")
    for path in ("/", "/schools", "/privacy", "/contact"):
        assert f"<loc>{_WEB_URL}{path}</loc>" in res.text
    # Only a "pick your schools" prompt without schools picked, so in no language.
    for path in ("/calendar", "/lunch"):
        for lang in ("", "/es", "/zh", "/ko", "/hi"):
            assert f"<loc>{_WEB_URL}{lang}{path}</loc>" not in res.text


@pytest.mark.anyio
async def test_sitemap_includes_school_slugs():
    async with database.SessionLocal() as db:
        district = District(name="Test District")
        db.add(district)
        await db.flush()
        db.add(School(name="Test Elementary", slug="test-elementary", school_type="elementary", district_id=district.id))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert f"<loc>{_WEB_URL}/schools/test-elementary</loc>" in res.text


@pytest.mark.anyio
async def test_prerender_rejects_unlisted_path():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/prerender", params={"path": "/admin"})
    assert res.status_code == 404


@pytest.mark.anyio
async def test_sitemap_pairs_translated_pages_with_hreflang():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert f"<loc>{_WEB_URL}/es</loc>" in res.text
    assert f"<loc>{_WEB_URL}/es/schools</loc>" in res.text
    assert f'hreflang="es" href="{_WEB_URL}/es/schools"' in res.text
    assert f'hreflang="x-default" href="{_WEB_URL}/schools"' in res.text
    assert f"<loc>{_WEB_URL}/zh/schools</loc>" in res.text
    assert f'hreflang="zh" href="{_WEB_URL}/zh/schools"' in res.text
    assert f'hreflang="ko" href="{_WEB_URL}/ko/schools"' in res.text
    assert f'hreflang="hi" href="{_WEB_URL}/hi/schools"' in res.text
    # No translation exists for these, so they must not be listed.
    assert f"{_WEB_URL}/zh/privacy" not in res.text
    assert f"{_WEB_URL}/es/privacy" not in res.text
    assert f"{_WEB_URL}/es/contact" not in res.text


def test_prerender_allows_language_prefixed_paths():
    import services.prerender as prerender

    assert prerender._is_allowed("/es")
    assert prerender._is_allowed("/es/schools/some-school")
    assert prerender._is_allowed("/es/lunch")
    assert prerender._is_allowed("/seasonal/halloween")
    assert prerender._is_allowed("/zh/schools/some-school")
    assert prerender._is_allowed("/es/schools/some-school/calendar")
    assert prerender._is_allowed("/ko/lunch")
    assert prerender._is_allowed("/hi")
    assert not prerender._is_allowed("/history")
    assert not prerender._is_allowed("/es/admin")
    assert not prerender._is_allowed("/essex")


@pytest.mark.anyio
async def test_sitemap_dates_school_pages_by_their_newest_content():
    from datetime import UTC, datetime

    async with database.SessionLocal() as db:
        district = District(name="Lastmod District")
        db.add(district)
        await db.flush()
        school = School(name="Lastmod Elementary", slug="lastmod-elementary", school_type="elementary", district_id=district.id)
        db.add(school)
        await db.flush()
        db.add(SchoolContentItem(scope="district", district_id=district.id, category="event", title="Board meeting", extracted_at=datetime(2031, 3, 4, 15, tzinfo=UTC)))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert f"<loc>{_WEB_URL}/schools/lastmod-elementary</loc><lastmod>2031-03-04</lastmod>" in res.text
    assert f"<loc>{_WEB_URL}/es/schools/lastmod-elementary</loc><lastmod>2031-03-04</lastmod>" in res.text
    # Its own calendar page, dated the same way, in every language.
    assert f"<loc>{_WEB_URL}/schools/lastmod-elementary/calendar</loc><lastmod>2031-03-04</lastmod>" in res.text
    assert f"<loc>{_WEB_URL}/ko/schools/lastmod-elementary/calendar</loc><lastmod>2031-03-04</lastmod>" in res.text
    # Static pages have no honest content date, so they carry none.
    assert f"<loc>{_WEB_URL}/privacy</loc></url>" in res.text


@pytest.mark.anyio
async def test_sitemap_paths_match_the_sitemap():
    from routers.seo import sitemap_paths

    async with database.SessionLocal() as db:
        paths = await sitemap_paths(db)
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    import re

    assert sorted(paths) == sorted(loc[len(_WEB_URL):] or "/" for loc in re.findall(r"<loc>([^<]+)</loc>", res.text))


@pytest.mark.anyio
async def test_sitemap_lists_each_district_budget_page_in_english_only():
    from datetime import UTC, datetime

    from models import DistrictBudget, StateDistrict

    async with database.SessionLocal() as db:
        state_district = StateDistrict(state="NJ", state_code="TSEO1", name="Seo Test District", slug="seo-test-district")
        db.add(state_district)
        await db.flush()
        db.add(DistrictBudget(state_district_id=state_district.id, budget_year="2026-27", source_commit="abcdef0", statements=[],
                              imported_at=datetime(2026, 10, 25, tzinfo=UTC)))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
        assert f"<loc>{_WEB_URL}/budgets</loc>" in res.text and f"<loc>{_WEB_URL}/es/budgets</loc>" in res.text
        assert f"<loc>{_WEB_URL}/budgets/seo-test-district</loc><lastmod>2026-10-25</lastmod></url>" in res.text
        assert f"{_WEB_URL}/es/budgets/seo-test-district" not in res.text
        # A crawler can have the page rendered; a made-up district can't.
        import services.prerender as prerender

        assert await prerender._names_something("/budgets/seo-test-district")
        assert not await prerender._names_something("/budgets/no-such-district")


@pytest.mark.anyio
async def test_sitemap_lists_localz_in_english_but_no_listing():
    from models import ResourceService

    async with database.SessionLocal() as db:
        listing = ResourceService(source="nj211", source_record_id="seo-test-1", name="Seo Test Pantry", categories=["food"])
        db.add(listing)
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    for path in ("/localz", "/localz/providers", "/localz/food", "/localz/everyday-needs", "/backpack-capture/privacy"):
        assert f"<loc>{_WEB_URL}{path}</loc></url>" in res.text
    assert f"{_WEB_URL}/es/localz" not in res.text
    assert "/localz/r/" not in res.text


@pytest.mark.anyio
async def test_sitemap_lists_a_season_until_it_is_over():
    from datetime import date, timedelta

    from models import SeasonalAttraction, SeasonalGuide
    from routers.seasonal_guides import today_et

    today = today_et()
    async with database.SessionLocal() as db:
        place = {"kind": "lights", "name": "A light show", "address": "1 Main St", "town": "Medford", "url": "https://example.org"}
        db.add(SeasonalAttraction(season="seotestrunning", starts_on=today + timedelta(days=10), ends_on=today + timedelta(days=40), **place))
        db.add(SeasonalAttraction(season="seotestover", starts_on=date(2020, 10, 1), ends_on=today - timedelta(days=1), **place))
        db.add(SeasonalGuide(season="seotestguide", title="Guide", publisher="A publisher", url="https://example.org/guide",
                             starts_on=today - timedelta(days=1), ends_on=today + timedelta(days=1)))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert f"<loc>{_WEB_URL}/seasonal/seotestrunning</loc></url>" in res.text
    assert f"<loc>{_WEB_URL}/seasonal/seotestguide</loc></url>" in res.text
    assert "/seasonal/seotestover" not in res.text


@pytest.mark.anyio
async def test_sitemap_lists_only_class_pages_with_something_on_them():
    from datetime import UTC, datetime

    from services.class_years import current_grad_years

    seniors, juniors, *_ = current_grad_years()
    async with database.SessionLocal() as db:
        busy = School(name="Seo Busy High", slug="seo-busy-high", school_type="high")
        quiet = School(name="Seo Quiet High", slug="seo-quiet-high", school_type="high")
        db.add_all([busy, quiet])
        await db.flush()
        db.add(SchoolContentItem(scope="school", school_id=busy.id, source="hs_announcements", category="event", title="Senior trip",
                                 applies_to_grad_years=[seniors], extracted_at=datetime(2031, 5, 6, tzinfo=UTC)))
        # A newsletter item lives on the school page, not a class page.
        db.add(SchoolContentItem(scope="school", school_id=quiet.id, source="newsletter", category="event", title="Bake sale"))
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        res = await client.get("/sitemap.xml")
    assert f"<loc>{_WEB_URL}/schools/seo-busy-high/class-of-{seniors}</loc><lastmod>2031-05-06</lastmod></url>" in res.text
    assert f"/schools/seo-busy-high/class-of-{juniors}" not in res.text
    assert "/schools/seo-quiet-high/class-of-" not in res.text
    # Class pages aren't translated.
    assert f"/es/schools/seo-busy-high/class-of-{seniors}" not in res.text
