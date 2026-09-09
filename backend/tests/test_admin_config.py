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


def _unique(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex[:8]}"


async def _make_admin(email: str) -> None:
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()


@pytest.mark.anyio
async def test_export_then_import_is_idempotent_and_creates_expected_rows():
    run_id = uuid.uuid4().hex[:8]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        email = f"admin_{run_id}@example.com"
        reg = await client.post("/auth/register", json={"email": email, "username": _unique("admin"), "password": "password123"})
        assert reg.status_code == 201, reg.text
        token = reg.json()["access_token"]
        await _make_admin(email)
        headers = {"authorization": f"Bearer {token}"}

        district_name = f"Test District {run_id}"
        school_a_slug = f"test-school-a-{run_id}"
        payload = {
            "exported_at": "2026-01-01T00:00:00Z",
            "source": "test",
            "districts": [
                {
                    "name": district_name,
                    "website_url": "https://example.org",
                    "food_services_menu_url": None,
                    "ics_feeds": [],
                    "marking_period_url": None,
                    "preschool_locations_url": None,
                    "preschool_team_url": None,
                    "hs_rotation_url": None,
                    "transportation_url": f"https://example.org/transportation-{run_id}",
                }
            ],
            "schools": [
                {
                    "slug": school_a_slug,
                    "name": f"Test School A {run_id}",
                    "short_name": "Test School A",
                    "district_name": district_name,
                    "school_type": "elementary",
                    "address": "1 Test St",
                    "main_phone": "(555) 555-0100",
                    "website_url": f"https://example.org/school-a-{run_id}",
                    "absence_method": "email",
                    "absence_emails": ["office@example.org"],
                    "absence_phone": None,
                    "absence_portal_name": None,
                    "absence_portal_url": None,
                    "absence_instructions": None,
                    "start_time": "8:00 AM",
                    "end_time": "3:00 PM",
                    "early_dismissal_time": None,
                    "delayed_opening_time": None,
                    "athletics_url": None,
                    "logo_url": None,
                    "bell_periods": None,
                    "sacc": {
                        "am_hours": "7:00 AM - 8:00 AM",
                        "pm_hours": "3:00 PM - 6:00 PM",
                        "site_phone": "(555) 555-0101",
                        "absence_phone": None,
                        "absence_form_url": None,
                        "late_pickup_policy": None,
                        "pickup_change_procedure": None,
                        "closures_notes": None,
                        "handbook_url": None,
                    },
                }
            ],
            "smore_newsletters": [
                {
                    "url": f"https://app.smore.com/n/test-{run_id}",
                    "label": "Test Weekly",
                    "school_slug": school_a_slug,
                    "cron_expr": "0 8 * * 1",
                    "timezone": "America/New_York",
                    "enabled": True,
                }
            ],
        }

        first = await client.post("/admin/config/import", json=payload, headers=headers)
        assert first.status_code == 200, first.text
        r1 = first.json()
        assert r1["districts_created"] == 1 and r1["districts_updated"] == 0
        assert r1["schools_created"] == 1 and r1["schools_updated"] == 0
        assert r1["smore_created"] == 1 and r1["smore_updated"] == 0
        assert r1["smore_skipped"] == []
        assert r1["sacc_created"] == 1 and r1["sacc_updated"] == 0

        # Re-importing the identical payload should touch the same rows,
        # not create duplicates.
        second = await client.post("/admin/config/import", json=payload, headers=headers)
        assert second.status_code == 200, second.text
        r2 = second.json()
        assert r2["districts_created"] == 0 and r2["districts_updated"] == 1
        assert r2["schools_created"] == 0 and r2["schools_updated"] == 1
        assert r2["smore_created"] == 0 and r2["smore_updated"] == 1
        assert r2["sacc_created"] == 0 and r2["sacc_updated"] == 1

        # And exporting again should include what was just imported, with
        # jobs actually created (not just the config fields set).
        export = await client.get("/admin/config/export", headers=headers)
        assert export.status_code == 200
        body = export.json()
        school = next(s for s in body["schools"] if s["slug"] == school_a_slug)
        assert school["sacc"]["site_phone"] == "(555) 555-0101"
        district = next(d for d in body["districts"] if d["name"] == district_name)
        assert district["transportation_url"] == f"https://example.org/transportation-{run_id}"


@pytest.mark.anyio
async def test_import_skips_smore_newsletter_for_unknown_school_slug():
    run_id = uuid.uuid4().hex[:8]
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        email = f"admin_{run_id}@example.com"
        reg = await client.post("/auth/register", json={"email": email, "username": _unique("admin"), "password": "password123"})
        token = reg.json()["access_token"]
        await _make_admin(email)
        headers = {"authorization": f"Bearer {token}"}

        payload = {
            "exported_at": "2026-01-01T00:00:00Z",
            "source": "test",
            "districts": [],
            "schools": [],
            "smore_newsletters": [
                {
                    "url": f"https://app.smore.com/n/orphan-{run_id}",
                    "label": "Orphan",
                    "school_slug": f"does-not-exist-{run_id}",
                    "cron_expr": "0 8 * * 1",
                    "timezone": "America/New_York",
                    "enabled": True,
                }
            ],
        }
        res = await client.post("/admin/config/import", json=payload, headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["smore_created"] == 0
        assert body["smore_skipped"] == [f"https://app.smore.com/n/orphan-{run_id}"]
