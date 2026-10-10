import os
import uuid
from datetime import datetime, timezone

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, func, select, update

import database
from main import app
from models import (
    ContentTranslation,
    District,
    JobRun,
    LunchMenu,
    LunchMenuItem,
    ScheduledJob,
    School,
    SchoolContentItem,
    SmoreBlock,
    SmoreNewsletter,
    StaffMember,
    User,
)
from scheduler.jobs.smore_scan import select_unseen_blocks
from services import contact_page, district_calendar_pdf


def _dt(day: int) -> datetime:
    return datetime(2026, 10, day, 4, tzinfo=timezone.utc)


async def _admin_client(client: AsyncClient, run_id: str) -> dict:
    email = f"admin_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"admin_{run_id}", "password": "password123"})
    assert reg.status_code == 201, reg.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"authorization": f"Bearer {reg.json()['access_token']}"}


def _config(run_id: str) -> dict:
    district = f"Results District {run_id}"
    slug = f"results-school-{run_id}"
    return {
        "exported_at": "2026-01-01T00:00:00Z",
        "source": "test",
        "districts": [
            {
                "name": district,
                "website_url": "https://example.org",
                "food_services_menu_url": f"https://example.org/food-{run_id}",
                "ics_feeds": [],
                "marking_period_url": None,
                "preschool_locations_url": None,
                "preschool_team_url": None,
                "hs_rotation_url": None,
                "transportation_url": None,
            }
        ],
        "schools": [
            {
                "slug": slug, "name": f"Results School {run_id}", "short_name": "Results", "district_name": district,
                "school_type": "elementary", "address": None, "main_phone": None, "website_url": None,
                "absence_method": None, "absence_emails": [], "absence_phone": None, "absence_portal_name": None,
                "absence_portal_url": None, "absence_instructions": None, "start_time": None, "end_time": None,
                "early_dismissal_time": None, "delayed_opening_time": None, "athletics_url": None, "logo_url": None,
                "bell_periods": None, "sacc": None,
            }
        ],
        "smore_newsletters": [
            {
                "url": f"https://app.smore.com/n/results-{run_id}", "label": "Weekly", "school_slug": slug,
                "cron_expr": "0 8 * * 1", "timezone": "America/New_York", "enabled": True,
            }
        ],
    }


async def _scan_locally(run_id: str, config: dict) -> None:
    """Rows the scans would have written in the exporting environment."""
    async with database.SessionLocal() as db:
        district = (await db.execute(select(District).where(District.name == config["districts"][0]["name"]))).scalar_one()
        school = (await db.execute(select(School).where(School.slug == config["schools"][0]["slug"]))).scalar_one()
        newsletter = (
            await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == config["smore_newsletters"][0]["url"]))
        ).scalar_one()

        text = SmoreBlock(newsletter_id=newsletter.id, position=0, block_type="text", text_content="Book fair Oct 20", content_hash=f"t{run_id}")
        image = SmoreBlock(
            newsletter_id=newsletter.id, position=1, block_type="image", image_url="https://cdn.example.org/flyer.png",
            content_hash=f"i{run_id}", pending_vision_extraction=False, vision_extracted_text="Picture day Oct 22",
        )
        db.add_all([text, image])
        await db.flush()

        old = SchoolContentItem(
            scope="school", school_id=school.id, newsletter_id=newsletter.id, source_block_id=text.id,
            category="event", title="Book fair", start_date=_dt(19), is_current=False,
        )
        new = SchoolContentItem(
            scope="school", school_id=school.id, newsletter_id=newsletter.id, source_block_id=text.id,
            category="event", title="Book Fair", start_date=_dt(20),
        )
        closed = SchoolContentItem(
            scope="district", district_id=district.id, newsletter_id=newsletter.id, source_block_id=image.id,
            category="event", title="Schools closed", start_date=_dt(12),
        )
        pdf = SchoolContentItem(
            scope="district", district_id=district.id, category="event", title="Winter break", start_date=_dt(24),
            source=district_calendar_pdf.SOURCE, external_uid=f"{district_calendar_pdf.UID_PREFIX}:abc{run_id}:1",
        )
        db.add_all([old, new, closed, pdf])
        await db.flush()
        old.superseded_by_id = new.id
        db.add(ContentTranslation(item_id=new.id, lang="es", title="Feria del libro", source_hash="h", model="m"))

        menu = LunchMenu(
            district_id=district.id, school_type="elementary", meal_type="lunch", period_label="October 2026",
            source_pdf_url=f"https://example.org/oct-{run_id}.pdf",
        )
        db.add(menu)
        await db.flush()
        db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=_dt(13), description="Pizza"))

        school.contact_page_hash = "c" * 64
        db.add(StaffMember(school_id=school.id, source_constituent_id=f"contact-page:nurse{run_id}@example.org", full_name="Pat Nurse", title="School Nurse"))
        db.add(StaffMember(school_id=school.id, source_constituent_id="12345", full_name="Sam Teacher", title="Teacher"))

        db.add(JobRun(job_id=newsletter.scheduled_job_id, status="success", triggered_by="manual", finished_at=_dt(9), log_excerpt="fetched 2 block(s), 2 new"))
        await db.commit()


async def _wipe_results(config: dict) -> None:
    """Back to what a freshly seeded environment holds: config and jobs only."""
    async with database.SessionLocal() as db:
        district = (await db.execute(select(District).where(District.name == config["districts"][0]["name"]))).scalar_one()
        school = (await db.execute(select(School).where(School.slug == config["schools"][0]["slug"]))).scalar_one()
        newsletter = (
            await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == config["smore_newsletters"][0]["url"]))
        ).scalar_one()
        await db.execute(
            delete(SchoolContentItem).where((SchoolContentItem.school_id == school.id) | (SchoolContentItem.district_id == district.id))
        )
        await db.execute(delete(SmoreBlock).where(SmoreBlock.newsletter_id == newsletter.id))
        await db.execute(delete(LunchMenu).where(LunchMenu.district_id == district.id))
        await db.execute(delete(StaffMember).where(StaffMember.school_id == school.id))
        await db.execute(delete(JobRun).where(JobRun.job_id == newsletter.scheduled_job_id))
        school.contact_page_hash = None
        await db.commit()


@pytest.mark.anyio
async def test_results_round_trip_leaves_the_first_scan_nothing_to_extract():
    run_id = uuid.uuid4().hex[:8]
    config = _config(run_id)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin_client(client, run_id)
        seeded = await client.post("/admin/config/import", json=config, headers=headers)
        assert seeded.status_code == 200, seeded.text
        await _scan_locally(run_id, config)

        exported = await client.get("/admin/config/results", params={"district": config["districts"][0]["name"]}, headers=headers)
        assert exported.status_code == 200, exported.text
        results = exported.json()
        assert [len(n["blocks"]) for n in results["newsletters"]] == [2]
        # Only the people read from the contact page travel, not the directory.
        assert [len(s["contact_staff"]) for s in results["schools"]] == [1]

        await _wipe_results(config)
        imported = await client.post("/admin/config/import", json={**config, "results": results}, headers=headers)
        assert imported.status_code == 200, imported.text
        body = imported.json()
        assert body["results_applied"] == {
            "contact_pages": 1, "lunch_menus": 1, "items": 4, "calendar_pdfs": 1, "blocks": 2, "newsletters": 1,
        }
        assert body["results_skipped"] == []

        async with database.SessionLocal() as db:
            newsletter = (
                await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == config["smore_newsletters"][0]["url"]))
            ).scalar_one()
            school = (await db.execute(select(School).where(School.slug == config["schools"][0]["slug"]))).scalar_one()
            blocks = (await db.execute(select(SmoreBlock).where(SmoreBlock.newsletter_id == newsletter.id))).scalars().all()
            # What smore.scan checks before extracting: every block is already on file.
            scanned = [{"content_hash": b.content_hash} for b in blocks]
            assert select_unseen_blocks(scanned, {b.content_hash for b in blocks}) == []
            assert {b.vision_extracted_text for b in blocks} == {None, "Picture day Oct 22"}

            items = {
                i.title: i
                for i in (await db.execute(select(SchoolContentItem).where(SchoolContentItem.newsletter_id == newsletter.id))).scalars()
            }
            assert items["Book fair"].superseded_by_id == items["Book Fair"].id and not items["Book fair"].is_current
            assert items["Book Fair"].source_block_id in {b.id for b in blocks}
            assert items["Schools closed"].district_id == school.district_id and items["Schools closed"].school_id is None
            translation = (await db.execute(select(ContentTranslation).where(ContentTranslation.item_id == items["Book Fair"].id))).scalar_one()
            assert translation.title == "Feria del libro"

            pdf = (
                await db.execute(
                    select(SchoolContentItem).where(
                        SchoolContentItem.district_id == school.district_id, SchoolContentItem.source == district_calendar_pdf.SOURCE
                    )
                )
            ).scalar_one()
            assert pdf.external_uid == f"{district_calendar_pdf.UID_PREFIX}:abc{run_id}:1"

            menu = (await db.execute(select(LunchMenu).where(LunchMenu.district_id == school.district_id))).scalar_one()
            assert (await db.execute(select(LunchMenuItem.description).where(LunchMenuItem.lunch_menu_id == menu.id))).scalars().all() == ["Pizza"]

            assert school.contact_page_hash == "c" * 64
            staff = (await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))).scalars().all()
            assert [(m.full_name, m.role) for m in staff] == [("Pat Nurse", "nurse")]

            # The job shows where its data came from, and still counts as never run.
            job = (await db.execute(select(ScheduledJob).where(ScheduledJob.id == newsletter.scheduled_job_id))).scalar_one()
            run = (await db.execute(select(JobRun).where(JobRun.job_id == job.id))).scalar_one()
            assert run.triggered_by == "imported" and run.status == "success" and "2 new" in run.log_excerpt
            assert job.last_run_at is None

        # A second import finds every source done and adds nothing.
        again = await client.post("/admin/config/import", json={**config, "results": results}, headers=headers)
        assert again.status_code == 200, again.text
        assert again.json()["results_applied"] == {}
        assert len(again.json()["results_skipped"]) == 2  # the newsletter and the calendar PDF say why
        async with database.SessionLocal() as db:
            count = (await db.execute(select(func.count(SmoreBlock.id)).where(SmoreBlock.newsletter_id == newsletter.id))).scalar_one()
            assert count == 2


@pytest.mark.anyio
async def test_results_export_needs_a_known_district():
    run_id = uuid.uuid4().hex[:8]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin_client(client, run_id)
        assert (await client.get("/admin/config/results", headers=headers)).status_code == 422
        missing = await client.get("/admin/config/results", params={"district": f"Nowhere {run_id}"}, headers=headers)
        assert missing.status_code == 404


@pytest.mark.anyio
async def test_unchanged_contact_page_skips_the_model(monkeypatch):
    home = '<a href="/contact">Contact Us</a>'
    page = '<div id="fsPageContent">Principal: Pat Lee pat@example.org</div>'

    async def fake_fetch(url, **_):
        return {"html": page if url.endswith("/contact") else home}

    def no_model(*_, **__):
        raise AssertionError("model called for an unchanged page")

    monkeypatch.setenv("ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(contact_page.scraper_client, "fetch_html", fake_fetch)
    monkeypatch.setattr(contact_page, "AsyncAnthropic", no_model)

    known_people = [{"constituent_id": "contact-page:pat@example.org", "email": "pat@example.org"}]
    digest = contact_page.text_hash(contact_page.page_text(page))
    people, returned = await contact_page.fetch_contacts("https://school.example.org", (digest, known_people))
    assert people == known_people and returned == digest

    with pytest.raises(AssertionError, match="model called"):
        await contact_page.fetch_contacts("https://school.example.org", ("stale", known_people))
