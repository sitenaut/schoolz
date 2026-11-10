"""An app connected to a family (routers/family_connections.py), the key it
collects (auth.FAMILY_KEY_ROUTES), and what it reads: GET /family/feed
(routers/family_feed.py)."""
import os
import uuid
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import (
    AuditEvent,
    Bucket3SyncState,
    ChildGradeEntry,
    ChildWorkItem,
    SchoolContentItem,
    SmoreNewsletter,
    StudentSpecial,
    User,
)

ET = ZoneInfo("America/New_York")


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


async def _register(client: AsyncClient, admin: bool = False) -> tuple[str, str]:
    email = f"feed_{uuid.uuid4().hex[:10]}@example.com"
    res = await client.post("/auth/register", json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"})
    assert res.status_code == 201, res.text
    if admin:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
    return email, res.json()["access_token"]


async def _school(client: AsyncClient, admin: str, district_id: str, school_type: str) -> dict:
    res = await client.post(
        "/schools",
        json={"name": f"Feed {school_type.title()} {uuid.uuid4().hex[:6]}", "school_type": school_type, "district_id": district_id},
        headers=_auth(admin),
    )
    assert res.status_code == 201, res.text
    return res.json()


async def _child(client: AsyncClient, guardian: str, first: str, school_id: str) -> str:
    res = await client.post(
        "/students",
        json={"first_name": first, "last_name": "Feedtest", "student_id": uuid.uuid4().hex[:8], "school_id": school_id},
        headers=_auth(guardian),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


async def _connect(client: AsyncClient, approver: str) -> dict:
    started = (await client.post("/family-connections/start", json={"client_name": "billz"})).json()
    assert started["approve_path"] == "/admin/connected-apps/approve" and len(started["user_code"]) == 9
    pending = await client.post("/family-connections/token", json={"device_code": started["device_code"]})
    assert pending.json() == {"status": "pending", "key": None, "connection_id": None}
    shown = await client.get(f"/admin/family-connections/requests/{started['user_code']}", headers=_auth(approver))
    assert shown.json()["client_name"] == "billz" and shown.json()["status"] == "pending", shown.text
    approved = await client.post(f"/admin/family-connections/requests/{started['user_code']}/approve", headers=_auth(approver))
    assert approved.json()["status"] == "approved", approved.text
    issued = (await client.post("/family-connections/token", json={"device_code": started["device_code"]})).json()
    assert issued["status"] == "approved" and issued["key"].startswith("szf_")
    # Collected once; the device code is spent.
    again = await client.post("/family-connections/token", json={"device_code": started["device_code"]})
    assert again.json()["status"] == "expired"
    return issued


def _weekday_after(d: date, n: int) -> date:
    """The n-th weekday after d (n >= 1)."""
    while n:
        d += timedelta(days=1)
        if d.weekday() < 5:
            n -= 1
    return d


def _on(d: date) -> datetime:
    return datetime.combine(d, time(0), ET)


@pytest.mark.anyio
async def test_only_billz_connects_and_only_a_super_admin_approves():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.post("/family-connections/start", json={"client_name": "Backpack Capture"})).status_code == 400
        started = (await client.post("/family-connections/start", json={"client_name": " billz "})).json()
        code = started["user_code"]

        # An ordinary guardian can't see or answer it; an anonymous caller neither.
        _email, guardian = await _register(client)
        assert (await client.get(f"/admin/family-connections/requests/{code}")).status_code == 401
        assert (await client.get(f"/admin/family-connections/requests/{code}", headers=_auth(guardian))).status_code == 403
        assert (await client.post(f"/admin/family-connections/requests/{code}/approve", headers=_auth(guardian))).status_code == 403

        _email, admin = await _register(client, admin=True)
        denied = await client.post(f"/admin/family-connections/requests/{code.lower()}/deny", headers=_auth(admin))
        assert denied.json()["status"] == "denied"
        token = await client.post("/family-connections/token", json={"device_code": started["device_code"]})
        assert token.json()["status"] == "denied"
        # Answered once is answered.
        late = await client.post(f"/admin/family-connections/requests/{code}/approve", headers=_auth(admin))
        assert late.status_code == 410
        assert (await client.get("/admin/family-connections/requests/BBBB-CCCC", headers=_auth(admin))).status_code == 404
        assert (await client.post("/family-connections/token", json={"device_code": "not-a-code"})).json()["status"] == "expired"


@pytest.mark.anyio
async def test_the_key_reads_the_feed_and_nothing_else():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, admin = await _register(client, admin=True)
        district = (await client.post("/districts", json={"name": f"Feed District {uuid.uuid4().hex[:8]}"}, headers=_auth(admin))).json()
        school = await _school(client, admin, district["id"], "elementary")
        child = await _child(client, admin, "Sample", school["id"])

        issued = await _connect(client, admin)
        # Whoever polls gets no account details with the key.
        assert set(issued) == {"status", "key", "connection_id"}
        key = _auth(issued["key"])
        assert (await client.get("/family/feed", headers=key)).status_code == 200
        for method, path in [
            ("GET", "/family"),
            ("GET", "/students"),
            ("GET", "/auth/me"),
            ("GET", f"/students/{child}/bucket3/todo"),
            ("GET", f"/students/{child}/specials"),
            ("POST", "/bucket3/import"),
            ("GET", "/admin/family-connections"),
            ("GET", "/admin/audit-log"),
        ]:
            res = await client.request(method, path, headers=key)
            assert res.status_code == 403, (method, path, res.status_code)

        # Listed for the person who approved it; removing it cuts it off.
        [listed] = (await client.get("/admin/family-connections", headers=_auth(admin))).json()
        assert listed["id"] == issued["connection_id"] and listed["name"] == "billz" and listed["last_used_at"] is not None
        _email, other_admin = await _register(client, admin=True)
        assert (await client.get("/admin/family-connections", headers=_auth(other_admin))).json() == []
        assert (await client.delete(f"/admin/family-connections/{listed['id']}", headers=_auth(other_admin))).status_code == 404
        assert (await client.delete(f"/admin/family-connections/{listed['id']}", headers=_auth(admin))).status_code == 204
        assert (await client.get("/family/feed", headers=key)).status_code == 401

        # The app's own Disconnect removes only itself, and a browser can't use it.
        mine, other = await _connect(client, admin), await _connect(client, admin)
        assert (await client.post("/family-connections/self/revoke", headers=_auth(admin))).status_code == 400
        assert (await client.post("/family-connections/self/revoke", headers=_auth(mine["key"]))).status_code == 204
        assert (await client.get("/family/feed", headers=_auth(mine["key"]))).status_code == 401
        assert (await client.get("/family/feed", headers=_auth(other["key"]))).status_code == 200

        async with database.SessionLocal() as db:
            rows = (await db.execute(select(AuditEvent.action, AuditEvent.credential))).all()
        assert {
            ("family_connection.approve", "session"),
            ("family_connection.revoke", "session"),
            ("family_connection.revoke_self", "family_key"),
        } <= set(rows)
        assert "family_connection.issued" in {action for action, _ in rows}


@pytest.mark.anyio
async def test_experimental_feed_is_for_super_admins_only():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, guardian = await _register(client)
        assert (await client.get("/family/feed", headers=_auth(guardian))).status_code == 403
        assert (await client.get("/family/feed")).status_code == 401

        email, admin = await _register(client, admin=True)
        issued = await _connect(client, admin)
        feed = (await client.get("/family/feed?start=2026-11-02&end=2026-11-06", headers=_auth(issued["key"]))).json()
        assert (feed["start"], feed["end"], feed["children"]) == ("2026-11-02", "2026-11-06", [])
        assert (await client.get("/family/feed?start=2026-11-10&end=2026-11-01", headers=_auth(admin))).status_code == 422
        assert (await client.get("/family/feed?start=2026-01-01&end=2026-12-31", headers=_auth(admin))).status_code == 422

        # No longer a super admin: the connection stops reading.
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=False))
            await db.commit()
        assert (await client.get("/family/feed", headers=_auth(issued["key"]))).status_code == 403


@pytest.mark.anyio
async def test_feed_carries_the_family_and_nothing_that_must_stay():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, admin = await _register(client, admin=True)
        district = (await client.post("/districts", json={"name": f"Feed District {uuid.uuid4().hex[:8]}"}, headers=_auth(admin))).json()
        elementary = await _school(client, admin, district["id"], "elementary")
        middle = await _school(client, admin, district["id"], "middle")
        younger = await _child(client, admin, "Robin", elementary["id"])
        older = await _child(client, admin, "Sky", middle["id"])
        # Another family at the same school: never in this feed.
        _email, stranger = await _register(client)
        await _child(client, stranger, "Other", elementary["id"])

        today = datetime.now(ET).date()
        rotation_on, closed_on, event_on = _weekday_after(today, 1), _weekday_after(today, 2), _weekday_after(today, 3)
        async with database.SessionLocal() as db:
            issue = SmoreNewsletter(url=f"https://app.smore.com/n/{uuid.uuid4().hex[:6]}", school_id=elementary["id"])
            db.add(issue)
            await db.flush()
            district_scope = {"scope": "district", "district_id": district["id"]}
            db.add_all(
                [
                    SchoolContentItem(**district_scope, category="event", title="Day 3", source="ics_feed", start_date=_on(rotation_on), applies_to_school_types=["elementary"]),
                    SchoolContentItem(**district_scope, category="event", title="Schools Closed - Thanksgiving Recess", source="ics_feed", start_date=_on(closed_on)),
                    SchoolContentItem(**district_scope, category="event", title="Board of Education Meeting", source="ics_feed", start_date=_on(event_on)),
                    SchoolContentItem(school_id=elementary["id"], category="event", title="Picture Day", source="newsletter", newsletter_id=issue.id, start_date=_on(event_on)),
                    SchoolContentItem(school_id=elementary["id"], category="volunteer", title="Book fair volunteers needed", source="newsletter", newsletter_id=issue.id),
                    SchoolContentItem(school_id=elementary["id"], category="person", title="Meet our new librarian", source="newsletter", newsletter_id=issue.id),
                    SchoolContentItem(school_id=elementary["id"], category="event", title="Varsity Soccer vs Rival", source="digitalsports", start_date=_on(event_on)),
                    StudentSpecial(student_id=younger, rotation_day=3, subject="Art", teacher="Room 12"),
                    Bucket3SyncState(student_id=older, classroom_seen_at=datetime.now(UTC)),
                    ChildWorkItem(
                        student_id=older,
                        external_uid=f"cw-{uuid.uuid4().hex[:8]}",
                        course_name="Science 7",
                        title="Lab report",
                        item_type="assignment",
                        due_date=_weekday_after(today, 4).isoformat(),
                        link="https://classroom.google.com/c/abc/a/def/details",
                    ),
                ]
            )
            await db.commit()

        res = await client.get("/family/feed", headers=_auth(admin))
        assert res.status_code == 200, res.text
        feed = res.json()

        # Children: first names and schools, never what identifies them further.
        assert [c["first_name"] for c in feed["children"]] == ["Robin", "Sky"]
        robin = next(c for c in feed["children"] if c["id"] == younger)
        assert robin["specials"] == [{"rotation_day": 3, "subject": "Art", "teacher": "Room 12"}]
        text = res.text
        for never in ("Feedtest", "student_id", "Other", "@example.com"):
            assert never not in text, never
        assert {s["id"] for s in feed["schools"]} == {elementary["id"], middle["id"]}

        by_uid = {i["uid"]: i for i in feed["items"]}
        assert len(by_uid) == len(feed["items"])
        day = by_uid[f"day:{elementary['id']}:{rotation_on.isoformat()}"]
        assert day["status"] == "open" and day["data"]["rotation_day"] == "Day 3"
        # The rotation feed is elementary's only.
        assert by_uid[f"day:{middle['id']}:{rotation_on.isoformat()}"]["data"]["rotation_day"] is None
        closed = by_uid[f"day:{middle['id']}:{closed_on.isoformat()}"]
        assert closed["status"] == "closed" and closed["title"] == "No school: Thanksgiving Recess"

        special = by_uid[f"schedule:{younger}:{rotation_on.isoformat()}"]
        assert special["title"] == "Day 3" and special["detail"] == "Art"

        titles = {i["title"]: i for i in feed["items"] if i["kind"] in ("event", "news")}
        assert "Day 3" not in titles and "Meet our new librarian" not in titles and "Varsity Soccer vs Rival" not in titles
        assert titles["Picture Day"]["kind"] == "event" and titles["Picture Day"]["data"]["newsletter_url"] == issue.url
        assert titles["Book fair volunteers needed"]["kind"] == "news"
        # A district item reaches both children's schools once.
        board = titles["Board of Education Meeting"]
        assert board["school_id"] is None and sorted(board["data"]["school_ids"]) == sorted([elementary["id"], middle["id"]])

        [work] = [i for i in feed["items"] if i["kind"] == "assignment"]
        assert work["child_id"] == older and work["status"] == "due" and work["data"]["course_name"] == "Science 7"
        assert "marked_by" not in work["data"] and "teacher_emails" not in work["data"]

        # The same data reads the same: uids and hashes are stable, and an
        # edit changes only that item's hash.
        again = {i["uid"]: i["hash"] for i in (await client.get("/family/feed", headers=_auth(admin))).json()["items"]}
        assert again == {uid: i["hash"] for uid, i in by_uid.items()}
        async with database.SessionLocal() as db:
            await db.execute(update(SchoolContentItem).where(SchoolContentItem.title == "Picture Day").values(title="Picture Day (retakes)"))
            await db.commit()
        edited = {i["uid"]: i["hash"] for i in (await client.get("/family/feed", headers=_auth(admin))).json()["items"]}
        changed = {uid for uid in edited if edited[uid] != again.get(uid)}
        assert changed == {titles["Picture Day"]["uid"]}


@pytest.mark.anyio
async def test_a_grade_is_news_from_when_it_was_graded():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _email, admin = await _register(client, admin=True)
        district = (await client.post("/districts", json={"name": f"Feed District {uuid.uuid4().hex[:8]}"}, headers=_auth(admin))).json()
        school = await _school(client, admin, district["id"], "high")
        child = await _child(client, admin, "Sample", school["id"])
        now = datetime.now(UTC)
        graded_at = now - timedelta(days=1)
        async with database.SessionLocal() as db:
            db.add_all(
                [
                    Bucket3SyncState(student_id=child, genesis_seen_at=now),
                    # Listed by List Assignments two days ago, nothing graded yet.
                    ChildGradeEntry(
                        student_id=child, external_uid="listed", course_code="121", course_section="1",
                        weekday_date="Mon 11/9", title="Essay Revisions", score_possible=5.0, first_seen_at=now - timedelta(days=2),
                    ),
                    # Listed a month ago, graded yesterday.
                    ChildGradeEntry(
                        student_id=child, external_uid="graded", course_code="331", course_section="10",
                        weekday_date="Thu 10/22", title="Periodic Table Quiz", score_earned=13.0, score_possible=45.0,
                        percent=28.9, first_seen_at=now - timedelta(days=30), graded_at=graded_at,
                    ),
                ]
            )
            await db.commit()
        feed = (await client.get("/family/feed", headers=_auth(admin))).json()
        [grade] = [i for i in feed["items"] if i["kind"] == "grade"]
        assert grade["title"] == "Periodic Table Quiz"
        assert datetime.fromisoformat(grade["data"]["graded_at"]) == graded_at
