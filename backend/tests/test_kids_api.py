"""End-to-end API tests for the Kids view v2 endpoints (routers/bucket3.py)."""
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import ChildWorkItem, ChildWorkItemProgress, StaffMember, User
from routers import bucket3 as bucket3_router
from services import kids_suggestions

ET = ZoneInfo("America/New_York")
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "bucket3")
FEED_URL = "https://classroom.google.com/u/2/w/AAAASLUG/t/all"
FEED_SID = "1234567"  # the fixture's Classroom login is 1234567@example.org


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _env(adapter: str, url: str, text: str, captured: str = "2026-09-14T13:00:00Z") -> dict:
    return {"adapter": adapter, "source_url": url, "reduced_text": text, "captured_at": captured, "status": "ok", "char_count": len(text)}


async def _register(client: AsyncClient, email: str) -> str:
    res = await client.post(
        "/auth/register", json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"}
    )
    assert res.status_code == 201, res.text
    return res.json()["access_token"]


async def _family(client: AsyncClient, student_id: str = FEED_SID, first_name: str = "Sample"):
    """A guardian, a school with one staff member, and one student."""
    run = uuid.uuid4().hex[:8]
    email = f"kidsapi_{run}@example.com"
    guardian = await _register(client, email)
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    school = (await client.post("/schools", json={"name": f"Kids API High {run}"}, headers=_auth(guardian))).json()
    async with database.SessionLocal() as db:
        db.add(StaffMember(school_id=school["id"], source_constituent_id=f"c-{run}", full_name="Pat Jones", email="PJones@example.org"))
        await db.commit()
    student = await client.post(
        "/students",
        json={"first_name": first_name, "last_name": "Student", "student_id": student_id, "school_id": school["id"]},
        headers=_auth(guardian),
    )
    assert student.status_code == 201, student.text
    return run, guardian, student.json()["id"]


async def _import(client: AsyncClient, token: str, sid: str, envelopes: list[dict]) -> dict:
    res = await client.post(f"/students/{sid}/bucket3/import", json={"captures": envelopes}, headers=_auth(token))
    assert res.status_code == 200, res.text
    return res.json()


def _freeze(monkeypatch, *args):
    monkeypatch.setattr(bucket3_router, "_local_now", lambda: datetime(*args, tzinfo=ET))


@pytest.mark.anyio
async def test_todo_categories_shared_marks_and_teacher_emails(monkeypatch):
    _freeze(monkeypatch, 2026, 9, 14, 9, 0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, sid = await _family(client)
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, _load("classroom_stream_feed.txt"))])

        todo = (await client.get(f"/students/{sid}/bucket3/todo", headers=_auth(guardian))).json()
        [pre] = todo["done"]
        assert pre["title"] == "Pre-Test Form"
        assert pre["done_source"] == "classroom"
        assert pre["classroom_status"] == "Graded"
        assert pre["teacher_emails"] == ["pjones@example.org"]
        [lab] = todo["due"]
        assert lab["title"].startswith("Lab Safety Contract")
        assert lab["due_date"] == "2026-09-18"
        # No teacher on the grid row itself - falls back to the course's poster.
        assert lab["teacher_emails"] == ["pjones@example.org"]
        assert todo["next_action"]["id"] == lab["id"]
        assert todo["progress"] == {"done": 1, "missing": 0, "due": 1, "total": 2, "percent": 50}
        assert all(i["item_type"] != "announcement" for bucket in ("missing", "due", "done", "no_due_date") for i in todo[bucket])

        # The student gets their own login and checks off the lab contract...
        kid_email = f"kid_{run}@example.com"
        invite = await client.post(
            f"/students/{sid}/account-invites", json={"invitee_email": kid_email}, headers=_auth(guardian)
        )
        kid = await _register(client, kid_email)
        await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(kid))
        marked = await client.post(
            f"/students/{sid}/bucket3/workitems/{lab['id']}/complete", json={"done": True}, headers=_auth(kid)
        )
        assert marked.status_code == 200, marked.text
        assert marked.json()["marked_by"] == "Sample"

        # ...and the guardian sees it, attributed to the student.
        todo = (await client.get(f"/students/{sid}/bucket3/todo", headers=_auth(guardian))).json()
        lab_done = next(i for i in todo["done"] if i["id"] == lab["id"])
        assert lab_done["done_source"] == "marked"
        assert lab_done["marked_by"] == "Sample"

        # The guardian unchecking a Classroom-"Graded" item beats Classroom.
        await client.post(
            f"/students/{sid}/bucket3/workitems/{pre['id']}/complete", json={"done": False}, headers=_auth(guardian)
        )
        todo = (await client.get(f"/students/{sid}/bucket3/todo", headers=_auth(kid))).json()
        assert [i["title"] for i in todo["missing"]] == ["Pre-Test Form"]
        assert todo["next_action"]["title"] == "Pre-Test Form"

        emails = (await client.get(f"/students/{sid}/bucket3/teacher-emails", headers=_auth(kid))).json()
        assert emails == {"Pat Jones": ["pjones@example.org"]}


@pytest.mark.anyio
async def test_announcements(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, _load("classroom_stream_feed.txt"))])
        [a] = (await client.get(f"/students/{sid}/bucket3/announcements", headers=_auth(guardian))).json()
        assert a["teacher_name"] == "Pat Jones"
        assert a["teacher_emails"] == ["pjones@example.org"]
        assert a["posted_date"] == "2026-09-03"
        assert "Bring your Chromebook" in a["body"]


@pytest.mark.anyio
async def test_right_now(monkeypatch):
    _freeze(monkeypatch, 2026, 9, 14, 8, 0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client, student_id="7654321")
        daily = _load("genesis_daily_view.txt").replace("9999999", "7654321")
        url = "https://parents.example.org/genesis/parents?tab1=studentdata&tab2=studentsummary&studentid=7654321"
        await _import(client, guardian, sid, [_env("genesis", url, daily)])

        now = (await client.get(f"/students/{sid}/bucket3/right-now", headers=_auth(guardian))).json()
        assert now["stale"] is False
        assert now["cycle_label"] == "1"
        assert now["current"]["period"] == "A"
        assert now["current"]["course_name"] == "GEOMETRY A"
        assert now["current"]["minutes_left"] == 27
        assert now["next"]["period"] == "B"

        _freeze(monkeypatch, 2026, 9, 15, 8, 0)
        stale = (await client.get(f"/students/{sid}/bucket3/right-now", headers=_auth(guardian))).json()
        assert stale["stale"] is True
        assert stale["current"] is None


@pytest.mark.anyio
async def test_progress_flags_low_grades(monkeypatch):
    _freeze(monkeypatch, 2026, 9, 14, 9, 0)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        grades_url = (
            "https://parents.example.org/genesis/parents?tab1=studentdata&tab2=gradebook&tab3=coursesummary"
            f"&studentid={FEED_SID}&courseCode=101&courseSection=1"
        )
        await _import(
            client,
            guardian,
            sid,
            [
                _env("classroom", FEED_URL, _load("classroom_stream_feed.txt")),
                _env("genesis", grades_url, _load("genesis_course_grades.txt")),
            ],
        )
        courses = (await client.get(f"/students/{sid}/bucket3/progress", headers=_auth(guardian))).json()
        algebra = next(c for c in courses if c["course_key"] == "101-1")
        assert algebra["course_name"] == "ALGEBRA I 101-1"
        assert algebra["grade_percent"] == 80.0
        assert {"title": "Vocab Worksheet", "percent": 0.0} in algebra["low_grade_entries"]
        assert algebra["teacher_emails"] == ["pjones@example.org"]


@pytest.mark.anyio
async def test_assignment_suggestion_is_cached_and_shared_across_the_class(monkeypatch):
    calls = []

    async def fake_suggestion(title, course_name):
        calls.append((title, course_name))
        return "- Open the form and read the first question", False

    monkeypatch.setattr(kids_suggestions, "assignment_suggestion", fake_suggestion)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, parent_a, sid_a = await _family(client)
        feed = _load("classroom_stream_feed.txt")
        await _import(client, parent_a, sid_a, [_env("classroom", FEED_URL, feed)])

        # A different family, same class section.
        other_sid = f"9{uuid.uuid4().int % 10**6:06d}"
        _run_b, parent_b, sid_b = await _family(client, student_id=other_sid, first_name="Other")
        await _import(client, parent_b, sid_b, [_env("classroom", FEED_URL, feed.replace(FEED_SID, other_sid))])

        lab_a = (await client.get(f"/students/{sid_a}/bucket3/todo", headers=_auth(parent_a))).json()["due"][0]
        first = await client.post(f"/students/{sid_a}/bucket3/suggestions/assignment/{lab_a['id']}", headers=_auth(parent_a))
        assert first.status_code == 200, first.text
        assert first.json() == {"text": "- Open the form and read the first question", "declined": False, "cached": False}
        # Only the title and course name are ever sent.
        assert calls == [(lab_a["title"], "ALGEBRA I 101-1")]

        lab_b = (await client.get(f"/students/{sid_b}/bucket3/todo", headers=_auth(parent_b))).json()["due"][0]
        assert lab_b["suggestion"]["text"] == "- Open the form and read the first question"
        second = await client.post(f"/students/{sid_b}/bucket3/suggestions/assignment/{lab_b['id']}", headers=_auth(parent_b))
        assert second.json()["cached"] is True
        assert len(calls) == 1

        # Another family can't touch this family's items.
        cross = await client.post(f"/students/{sid_b}/bucket3/suggestions/assignment/{lab_a['id']}", headers=_auth(parent_b))
        assert cross.status_code == 404


@pytest.mark.anyio
async def test_plan_sends_only_open_items_and_503_without_key(monkeypatch):
    _freeze(monkeypatch, 2026, 9, 14, 9, 0)
    seen = {}

    async def fake_plan(items, today):
        seen["titles"] = [i["title"] for i in items]
        seen["today"] = today
        return "1. **Lab Safety Contract** - due Friday"

    monkeypatch.setattr(kids_suggestions, "plan", fake_plan)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, _load("classroom_stream_feed.txt"))])
        res = await client.post(f"/students/{sid}/bucket3/suggestions/plan", headers=_auth(guardian))
        assert res.status_code == 200, res.text
        assert res.json()["text"].startswith("1.")
        assert len(seen["titles"]) == 1 and seen["titles"][0].startswith("Lab Safety Contract")
        assert seen["today"] == "2026-09-14"

        async def unavailable(*_args):
            raise kids_suggestions.SuggestionsUnavailable("no key")

        monkeypatch.setattr(kids_suggestions, "plan", unavailable)
        res = await client.post(f"/students/{sid}/bucket3/suggestions/plan", headers=_auth(guardian))
        assert res.status_code == 503


@pytest.mark.anyio
async def test_reprocess_reapplies_current_parsing_and_prunes_stale_rows(monkeypatch):
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, _load("classroom_stream_feed.txt"))])

        async with database.SessionLocal() as db:
            # Simulate rows written by an older parser: fields missing, plus a
            # title-hash duplicate that current parsing no longer produces.
            await db.execute(
                update(ChildWorkItem).where(ChildWorkItem.student_id == sid).values(teacher_name=None, status=None)
            )
            db.add(ChildWorkItem(student_id=sid, external_uid="hash:AAAASLUG:Pre-Test Form", title="Pre-Test Form", item_type="assignment"))
            kept = ChildWorkItem(student_id=sid, external_uid="hash:AAAASLUG:Marked Thing", title="Marked Thing", item_type="assignment")
            db.add(kept)
            await db.flush()
            db.add(ChildWorkItemProgress(student_id=sid, work_item_id=kept.id, done=True))
            await db.commit()

        res = await client.post(f"/students/{sid}/bucket3/reprocess", headers=_auth(guardian))
        assert res.status_code == 200, res.text

        async with database.SessionLocal() as db:
            rows = {w.external_uid: w for w in (await db.execute(select(ChildWorkItem).where(ChildWorkItem.student_id == sid))).scalars().all()}
        assert rows["si:900010"].teacher_name == "Pat Jones"
        assert rows["si:900010"].status == "Graded"
        assert "hash:AAAASLUG:Pre-Test Form" not in rows
        assert "hash:AAAASLUG:Marked Thing" in rows  # someone marked it - never silently dropped


@pytest.mark.anyio
async def test_kids_endpoints_require_access():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        stranger = await _register(client, f"stranger_{uuid.uuid4().hex[:8]}@example.com")
        for path in ("right-now", "todo", "progress", "announcements", "teacher-emails"):
            assert (await client.get(f"/students/{sid}/bucket3/{path}", headers=_auth(stranger))).status_code == 404
        assert (await client.post(f"/students/{sid}/bucket3/reprocess", headers=_auth(stranger))).status_code == 404
