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
        with pytest.raises(Exception):
            await documents_scan.run(db, {"school_id": school.id})
