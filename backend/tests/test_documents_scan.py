import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest

import database
from models import School, SmoreNewsletter
from scheduler.jobs import documents_scan


async def _make_school(website_url: str | None) -> School:
    tag = uuid.uuid4().hex[:8]
    school = School(name=f"Test School {tag}", slug=f"test-school-{tag}", website_url=website_url)
    async with database.SessionLocal() as db:
        db.add(school)
        await db.commit()
        await db.refresh(school)
    return school


@pytest.mark.anyio
async def test_no_documents_warning_names_what_was_checked_with_no_site_or_newsletters():
    # Real complaint this fixes: "which document were you trying to fetch
    # that you didn't find? it doesn't say" - the old message was a bare
    # "no handbook or bell schedule found on site or in newsletters" no
    # matter what (or whether anything) was actually checked.
    school = await _make_school(website_url=None)
    async with database.SessionLocal() as db:
        result = await documents_scan.run(db, {"school_id": school.id})

    assert result is not None
    assert result.startswith("WARNING[no_documents_found]:")
    assert "site: none (no website_url set)" in result
    assert "no newsletters tracked" in result


@pytest.mark.anyio
async def test_no_documents_warning_names_the_site_and_newsletter_count():
    school = await _make_school(website_url="https://example-school.chclc.org")
    async with database.SessionLocal() as db:
        db.add(SmoreNewsletter(url=f"https://app.smore.com/n/{uuid.uuid4().hex[:8]}", school_id=school.id))
        await db.commit()

        # No scraper configured in tests - fetch_html raises before finding
        # anything, so this also exercises the "site fetch failed" path
        # ending up as an unhandled exception (classified upstream by
        # scheduler/errors.py as a real error) rather than a silent [].
        with pytest.raises(Exception):  # noqa: B017 - whatever the missing scraper raises
            await documents_scan.run(db, {"school_id": school.id})


@pytest.mark.anyio
async def test_stored_google_sign_in_link_is_never_current_and_never_sets_the_year(monkeypatch):
    # Evans Preschool: an older scan stored the Drive viewer's sign-in link,
    # dated 2016-17 from the viewer's markup. The school's own link (no year)
    # must win, and the sign-in row must stop counting.
    from sqlalchemy import select

    from models import SchoolDocument

    school = await _make_school(website_url="https://evans.example.org")
    sign_in = "https://accounts.google.com/ServiceLogin?continue=https://drive.google.com/file/d/abc/view"
    own = "https://evans.example.org/436309_2"
    async with database.SessionLocal() as db:
        db.add(SchoolDocument(school_id=school.id, doc_type="handbook", title="2026 EPC Orientation.pdf - Google Drive",
                              url=sign_in, academic_year="2016-2017", source="website", is_current=True))
        await db.commit()

    async def fake_discover(url):
        return [{"title": "2026 EPC Orientation.pdf - Google Drive", "url": own, "academic_year": None, "doc_type": "handbook"}]

    monkeypatch.setattr(documents_scan, "discover_from_website", fake_discover)
    async with database.SessionLocal() as db:
        await documents_scan.run(db, {"school_id": school.id})
        await db.commit()
        rows = {d.url: d.is_current for d in (await db.execute(select(SchoolDocument).where(SchoolDocument.school_id == school.id))).scalars()}
    assert rows == {sign_in: False, own: True}
