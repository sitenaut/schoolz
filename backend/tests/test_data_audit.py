import os
import uuid
from datetime import UTC, date, datetime, timedelta

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import District, JobRun, ScheduledJob, School, SchoolDocument, SmoreNewsletter, User
from services import data_audit

pytestmark = pytest.mark.anyio
NOW = datetime.now(UTC)


async def _register(client: AsyncClient, prefix: str, *, super_admin: bool = False) -> dict:
    run_id = uuid.uuid4().hex[:8]
    email = f"{prefix}_{run_id}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": f"{prefix}_{run_id}", "password": "password123"})
    assert reg.status_code == 201, reg.text
    if super_admin:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
    return {"authorization": f"Bearer {reg.json()['access_token']}"}


async def _with_role(client: AsyncClient, boss: dict, prefix: str, perms: list[str]) -> dict:
    headers = await _register(client, prefix)
    me = (await client.get("/auth/me", headers=headers)).json()
    role = (await client.post("/admin/roles", headers=boss, json={"name": f"{prefix} {uuid.uuid4().hex[:6]}", "permissions": perms})).json()
    res = await client.put(f"/admin/users/{me['id']}/roles", headers=boss, json={"role_ids": [role["id"]]})
    assert res.status_code == 200, res.text
    return headers


def _job(kind: str, cron: str, **params) -> ScheduledJob:
    return ScheduledJob(kind=kind, name=f"{kind} {uuid.uuid4().hex[:6]}", cron_expr=cron, params=params, enabled=True)


def _run(job: ScheduledJob, status: str, ago: timedelta, code: str | None = None) -> JobRun:
    at = NOW - ago
    return JobRun(job_id=job.id, status=status, started_at=at, finished_at=at, error_code=code, triggered_by="cron")


async def _seed() -> dict:
    """Two districts. In the first, a high school with one data point in
    each status and an elementary school; the second has one school."""
    tag = uuid.uuid4().hex[:6]
    async with database.SessionLocal() as db:
        d1 = District(name=f"Audit District {tag}")
        d2 = District(name=f"Other District {tag}")
        db.add_all([d1, d2])
        await db.flush()

        info = _job("school_info.scan", "5 3 7 * *")  # monthly
        roster = _job("staff_roster.scan", "5 3 1,15 * *")  # twice a month
        docs = _job("documents.scan", "5 3 2,16 * *")
        news = _job("smore.scan", "7 8 * * 1")
        db.add_all([info, roster, docs, news])
        await db.flush()

        high = School(
            name=f"Audit High {tag}", slug=f"audit-high-{tag}", district_id=d1.id, school_type="high",
            address="1 Main St", main_phone="555-0100", start_time="7:30 AM", end_time="2:15 PM",
            school_info_job_id=info.id, staff_roster_job_id=roster.id, documents_scan_job_id=docs.id,
        )
        elem = School(name=f"Audit Elementary {tag}", slug=f"audit-elem-{tag}", district_id=d1.id, school_type="elementary")
        other = School(name=f"Other Elementary {tag}", slug=f"other-elem-{tag}", district_id=d2.id, school_type="elementary")
        db.add_all([high, elem, other])
        await db.flush()

        newsletter = SmoreNewsletter(url=f"https://www.smore.com/n/{tag}", school_id=high.id, source_type="smore", scheduled_job_id=news.id)
        db.add(newsletter)
        db.add(SchoolDocument(school_id=high.id, doc_type="handbook", title="Handbook", url=f"https://example.com/{tag}.pdf",
                              academic_year=f"{data_audit.school_year_start(date.today()).year}-{data_audit.school_year_start(date.today()).year + 1}",
                              source="website"))
        db.add_all([
            _run(info, "success", timedelta(days=3)),  # address current, logo missing -> failing
            _run(roster, "success", timedelta(days=40)),
            _run(roster, "error", timedelta(days=2), "site_did_not_load"),  # failing
            _run(docs, "success", timedelta(days=50)),  # handbook stale (35-day window)
            _run(news, "warning", timedelta(days=1), "smore_no_blocks"),  # failing, never scanned
        ])
        await db.commit()
        return {"d1": d1.id, "d2": d2.id, "high": high.id, "elem": elem.id, "other": other.id, "roster": roster.id}


async def _boss(client: AsyncClient) -> dict:
    return await _register(client, "auditboss", super_admin=True)


async def test_each_status_and_not_applicable_left_out_of_score():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = await _seed()
        boss = await _boss(client)
        res = await client.get(f"/admin/audit/schools/{ids['high']}", headers=boss)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["audience"] == "internal"
        cells = body["school"]["cells"]
        assert cells["info"]["status"] == "current"
        assert cells["hours"]["status"] == "current"
        assert cells["logo"]["status"] == "failing"
        assert cells["staff"]["status"] == "failing" and cells["staff"]["error_code"] == "site_did_not_load"
        assert cells["staff"]["job_ids"] == [ids["roster"]]
        assert cells["hand"]["status"] == "stale"
        assert cells["news"]["status"] == "failing" and "smore_no_blocks" in cells["news"]["why"]
        assert cells["absence"]["status"] == "not_collecting"
        assert cells["care"]["status"] == "not_applicable"  # elementary only
        assert cells["pkteam"]["status"] == "not_applicable"

        counts = body["school"]["counts"]
        assert counts["not_applicable"] == 2  # before/after care and preschool team
        assert counts["applicable"] == 26 - counts["not_applicable"]
        assert counts["pct"] == round(100 * counts["current"] / counts["applicable"])

        elem = (await client.get(f"/admin/audit/schools/{ids['elem']}", headers=boss)).json()["school"]["cells"]
        for key in ("rot", "ann", "actcal", "actsite", "periods", "bulletin", "ath", "pkteam"):
            assert elem[key]["status"] == "not_applicable", key


async def test_district_filter_narrows_results():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = await _seed()
        boss = await _boss(client)
        all_ids = {s["id"] for s in (await client.get("/admin/audit", headers=boss)).json()["schools"]}
        assert {ids["high"], ids["elem"], ids["other"]} <= all_ids
        d1 = (await client.get("/admin/audit", headers=boss, params={"district_id": ids["d1"]})).json()
        assert {s["id"] for s in d1["schools"]} == {ids["high"], ids["elem"]}
        points = (await client.get("/admin/audit/data-points", headers=boss, params={"district_id": ids["d2"]})).json()
        assert points["school_count"] == 1
        csv_text = (await client.get("/admin/audit/export.csv", headers=boss, params={"district_id": ids["d2"]})).text
        assert "Other Elementary" in csv_text and "Audit High" not in csv_text


async def test_view_only_reads_district_audience_and_cannot_mutate(monkeypatch):
    started: list[str] = []
    monkeypatch.setattr("scheduler.runner.run_job_now", started.append)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = await _seed()
        boss = await _boss(client)
        viewer = await _with_role(client, boss, "auditviewer", ["audit.view"])

        # Asking for the internal audience doesn't get it.
        for path, params in (("/admin/audit", {"detail": "true", "audience": "internal"}),
                             (f"/admin/audit/schools/{ids['high']}", {"audience": "internal"}),
                             ("/admin/audit/data-points", {"audience": "internal"})):
            res = await client.get(path, headers=viewer, params=params)
            assert res.status_code == 200, res.text
            assert res.json()["audience"] == "district"
            text = res.text
            for leaked in ("site_did_not_load", "smore_no_blocks", "staff_roster.scan", "documents.scan", ids["roster"],
                           "error_code", "job_ids", "why_district", "next_district", "Internal:"):
                assert leaked not in text, (path, leaked)

        cells = (await client.get(f"/admin/audit/schools/{ids['high']}", headers=viewer)).json()["school"]["cells"]
        assert set(cells["staff"]) == {"key", "status", "tag", "why", "next", "last_good", "last_label", "collected_by", "runs", "stale_after", "internal_only"}
        assert cells["staff"]["status"] == "failing"  # same status, neutral words
        assert cells["news"]["next"] == "A link to a current issue."

        csv_text = (await client.get("/admin/audit/export.csv", headers=viewer, params={"audience": "internal"})).text
        assert "site_did_not_load" not in csv_text and "Error code" not in csv_text

        for method, path in (("post", f"/admin/audit/schools/{ids['high']}/data-points/staff/run"),
                             ("post", f"/admin/audit/schools/{ids['high']}/run-all"),
                             ("put", f"/admin/audit/schools/{ids['high']}/data-points/periods/not-published"),
                             ("delete", f"/admin/audit/schools/{ids['high']}/data-points/periods/not-published")):
            assert (await client.request(method, path, headers=viewer)).status_code == 403, path
        assert started == []

        # No audit permission at all: no read either.
        nobody = await _register(client, "auditnobody")
        assert (await client.get("/admin/audit", headers=nobody)).status_code == 403


async def test_public_audit_needs_no_account_and_is_district_wording_only(monkeypatch):
    started: list[str] = []
    monkeypatch.setattr("scheduler.runner.run_job_now", started.append)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = await _seed()
        boss = await _boss(client)
        for path, params in (("/audit", {"detail": "true", "audience": "internal"}),
                             (f"/audit/schools/{ids['high']}", {"audience": "internal"}),
                             ("/audit/data-points", {"audience": "internal"}),
                             ("/audit/export.csv", {"audience": "internal"})):
            # Anonymous, and a super admin too: the public paths only ever speak district.
            for headers in ({}, boss):
                res = await client.get(path, headers=headers, params=params)
                assert res.status_code == 200, res.text
                text = res.text
                for leaked in ("site_did_not_load", "smore_no_blocks", "staff_roster.scan", "documents.scan", ids["roster"],
                               "error_code", "job_ids", "why_district", "next_district", "Error code"):
                    assert leaked not in text, (path, leaked)
        body = (await client.get(f"/audit/schools/{ids['high']}")).json()
        assert body["audience"] == "district" and body["school"]["cells"]["staff"]["status"] == "failing"
        assert {s["id"] for s in (await client.get("/audit", params={"district_id": ids["d2"]})).json()["schools"]} == {ids["other"]}

        # Nothing that changes state is reachable without audit.manage.
        for method, path in (("post", f"/audit/schools/{ids['high']}/run-all"),
                             ("post", f"/admin/audit/schools/{ids['high']}/run-all"),
                             ("put", f"/admin/audit/schools/{ids['high']}/data-points/periods/not-published")):
            assert (await client.request(method, path)).status_code in (401, 403, 404, 405), path
        assert started == []


async def test_manage_can_mutate_and_preview_district_audience(monkeypatch):
    started: list[str] = []
    monkeypatch.setattr("scheduler.runner.run_job_now", started.append)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = await _seed()
        boss = await _boss(client)
        manager = await _with_role(client, boss, "auditmanager", ["audit.manage"])
        me = (await client.get("/auth/me", headers=manager)).json()
        assert {"audit.manage", "audit.view"} <= set(me["permissions"])

        internal = (await client.get(f"/admin/audit/schools/{ids['high']}", headers=manager)).json()
        assert internal["audience"] == "internal" and internal["school"]["cells"]["staff"]["error_code"] == "site_did_not_load"
        preview = (await client.get(f"/admin/audit/schools/{ids['high']}", headers=manager, params={"audience": "district"})).json()
        assert preview["audience"] == "district" and "error_code" not in preview["school"]["cells"]["staff"]

        res = await client.post(f"/admin/audit/schools/{ids['high']}/data-points/staff/run", headers=manager)
        assert res.status_code == 200, res.text
        assert started == [ids["roster"]]
        assert (await client.post(f"/admin/audit/schools/{ids['high']}/data-points/periods/run", headers=manager)).status_code == 409
        res = await client.post(f"/admin/audit/schools/{ids['high']}/run-all", headers=manager)
        assert res.status_code == 200 and len(res.json()["started"]) == 4

        res = await client.put(f"/admin/audit/schools/{ids['high']}/data-points/periods/not-published", headers=manager, json={"note": "Confirmed by the office"})
        assert res.status_code == 200, res.text
        cell = (await client.get(f"/admin/audit/schools/{ids['high']}", headers=manager)).json()["school"]["cells"]["periods"]
        assert cell["status"] == "not_collecting" and cell["tag"] == "not published" and cell["not_published"] is True
        district_cell = (await client.get(f"/admin/audit/schools/{ids['high']}", headers=manager, params={"audience": "district"})).json()["school"]["cells"]["periods"]
        assert district_cell["tag"] == "not published" and "isn't published" in district_cell["why"]

        assert (await client.delete(f"/admin/audit/schools/{ids['high']}/data-points/periods/not-published", headers=manager)).status_code == 200
        cell = (await client.get(f"/admin/audit/schools/{ids['high']}", headers=manager)).json()["school"]["cells"]["periods"]
        assert cell["tag"] == "no source set"


def test_cadence_tiers_follow_the_jobs_cron():
    assert data_audit.cadence_for_cron("0 6-18/2 * * 1-5").stale_after == "1 school day"
    assert data_audit.cadence_for_cron("17 */12 * * *").stale_after == "36 hours"
    assert data_audit.cadence_for_cron("17 4 * * *").stale_after == "3 days"
    assert data_audit.cadence_for_cron("17 8 * * 1").stale_after == "16 days"
    assert data_audit.cadence_for_cron("17 3 9,23 * *").stale_after == "35 days"
    assert data_audit.cadence_for_cron("17 3 9 * *").stale_after == "65 days"


def test_one_school_day_window_skips_weekends():
    cadence = data_audit.cadence_for_cron("0 6-18/2 * * 1-5")
    friday = datetime(2026, 10, 9, 18, 0, tzinfo=data_audit.TZ)
    assert not data_audit.is_past_window(friday, cadence, datetime(2026, 10, 12, 9, 0, tzinfo=data_audit.TZ))  # Monday
    assert data_audit.is_past_window(friday, cadence, datetime(2026, 10, 14, 9, 0, tzinfo=data_audit.TZ))  # Wednesday


async def test_public_wording_never_claims_more_than_we_know():
    """Each district-wording branch fixed after checking every school in prod."""
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        ids = await _seed()
        tag = uuid.uuid4().hex[:6]
        async with database.SessionLocal() as db:
            menu = _job("lunch_menu.scan", "17 4 * * *")
            db.add(menu)
            await db.flush()
            await db.execute(update(District).where(District.id == ids["d2"]).values(scheduled_job_id=menu.id))
            db.add(_run(menu, "success", timedelta(hours=5)))
            # A preschool with its address entered by hand and no website, so no scans.
            pre = School(name=f"Hand Preschool {tag}", slug=f"hand-pre-{tag}", district_id=ids["d2"], school_type="other",
                         address="2 Main St", main_phone="555-0101")
            db.add(pre)
            await db.commit()
        cells = (await client.get(f"/audit/schools/{pre.id}")).json()["school"]["cells"]
        assert cells["info"]["status"] == "current" and cells["info"]["collected_by"] == "Entered by hand"
        assert cells["info"]["runs"] == "No scan" and "entered by hand" in cells["info"]["why"]
        assert cells["geo"]["why"] == "We have the school's address but haven't placed it on a map yet."
        assert cells["hand"]["why"] == "We don't have a website for this school to look for a handbook on."
        assert cells["alt"]["why"] == "We don't have this school's early-dismissal and delayed-opening times."
        # District menus are scanned, but none has ever covered this school: a gap, not stale.
        assert cells["menu"]["status"] == "not_collecting" and "don't cover this school" in cells["menu"]["why"]

        high = (await client.get(f"/audit/schools/{ids['high']}")).json()["school"]["cells"]
        # Our own error: nothing asked of the district, nothing promised.
        assert high["staff"]["why"] == "We couldn't read the published source on our last check."
        assert high["staff"]["next"] == "Nothing needed from the district for now."
        assert high["logo"]["why"] == "Our last check of the published source didn't find this."
