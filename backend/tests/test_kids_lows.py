"""Bug sweep 2026-10-23 lows in the Kids View: reprocess deleting what
people entered or what a deleted co-guardian's captures produced (F50), and
an older capture applied after a newer one (F51)."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from main import app
from models import ChildGradeEntry, ChildWorkItem, HelpRequest, Student, WorkItemLateException
from tests.test_kids_api import FEED_SID, FEED_URL, _auth, _env, _family, _import, _load, _register

pytestmark = pytest.mark.anyio

FEED = _load("classroom_stream_feed.txt")
# The same page before the lab contract was posted.
FEED_WITHOUT_LAB = FEED.split("(data-include-stream-item-materials: true) (data-draggable-item-id: 900030)")[0]
GRADES_URL = (
    "https://parents.example.org/genesis/parents?tab1=studentdata&tab2=gradebook&tab3=coursesummary"
    f"&studentid={FEED_SID}&courseCode=101&courseSection=1"
)


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def _items(sid: str) -> dict[str, ChildWorkItem]:
    async with database.SessionLocal() as db:
        rows = (await db.execute(select(ChildWorkItem).where(ChildWorkItem.student_id == sid))).scalars().all()
    return {r.external_uid: r for r in rows}


async def test_an_older_capture_arriving_late_does_not_move_a_due_date_back():
    async with _client() as client:
        _run, guardian, sid = await _family(client)
        moved = FEED.replace("Due Fri, Sep 18, 11:59 PM", "Due Fri, Sep 25, 11:59 PM")
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, moved, "2026-09-14T15:00:00Z")])
        # The other computer's capture from two hours earlier publishes now.
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, FEED, "2026-09-14T13:00:00Z")])
        assert (await _items(sid))["si:900030"].due_date == "2026-09-25"

        # In order, the newer reading still wins as before.
        later = FEED.replace("Due Fri, Sep 18, 11:59 PM", "Due Fri, Oct 2, 11:59 PM")
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, later, "2026-09-15T13:00:00Z")])
        assert (await _items(sid))["si:900030"].due_date == "2026-10-02"


async def test_an_older_gradebook_page_does_not_put_back_an_old_grade():
    async with _client() as client:
        _run, guardian, sid = await _family(client)
        graded = _load("genesis_course_grades.txt").replace("8 / 10\n80.00%", "10 / 10\n100.00%")
        await _import(client, guardian, sid, [_env("genesis", GRADES_URL, graded, "2026-09-14T15:00:00Z")])
        await _import(client, guardian, sid, [_env("genesis", GRADES_URL, _load("genesis_course_grades.txt"), "2026-09-14T13:00:00Z")])
        async with database.SessionLocal() as db:
            quiz = (
                await db.execute(select(ChildGradeEntry).where(ChildGradeEntry.student_id == sid, ChildGradeEntry.title == "Reading Quiz"))
            ).scalar_one()
        assert quiz.percent == 100.0


async def test_reprocess_keeps_an_item_with_a_teacher_exception_or_a_help_request():
    async with _client() as client:
        _run, guardian, sid = await _family(client)
        await _import(client, guardian, sid, [_env("classroom", FEED_URL, FEED, "2026-09-14T13:00:00Z")])
        pre = (await _items(sid))["si:900010"]
        # Rows an older parser wrote from the same capture, which current
        # parsing no longer produces: one bare, two that people added to.
        same = {"course_external_id": pre.course_external_id, "last_seen_at": pre.last_seen_at, "item_type": "assignment"}
        async with database.SessionLocal() as db:
            rows = {name: ChildWorkItem(student_id=sid, external_uid=f"hash:AAAASLUG:{name}", title=name, **same) for name in ("bare", "excepted", "asked")}
            db.add_all(rows.values())
            await db.flush()
            db.add(WorkItemLateException(student_id=sid, work_item_id=rows["excepted"].id, accepted_until="2026-11-10"))
            db.add(HelpRequest(student_id=sid, work_item_id=rows["asked"].id, kind="how_to_start"))
            await db.commit()

        assert (await client.post(f"/students/{sid}/bucket3/reprocess", headers=_auth(guardian))).status_code == 200
        items = await _items(sid)
        assert "hash:AAAASLUG:bare" not in items
        assert "hash:AAAASLUG:excepted" in items and "hash:AAAASLUG:asked" in items


async def test_a_co_guardian_deleting_their_account_leaves_the_childs_work_through_reprocess():
    async with _client() as client:
        _run, first, sid = await _family(client)
        async with database.SessionLocal() as db:
            school_id = (await db.execute(select(Student.school_id).where(Student.id == sid))).scalar_one()
        second = await _register(client, f"coparent_{uuid.uuid4().hex[:8]}@example.com")
        linked = await client.post(
            "/students",
            json={"first_name": "Sample", "last_name": "Student", "student_id": FEED_SID, "school_id": school_id},
            headers=_auth(second),
        )
        assert linked.json()["id"] == sid

        # The second guardian looked once, before the lab was posted; the
        # first kept looking, then left.
        await _import(client, second, sid, [_env("classroom", FEED_URL, FEED_WITHOUT_LAB, "2026-09-10T13:00:00Z")])
        await _import(client, first, sid, [_env("classroom", FEED_URL, FEED, "2026-09-14T13:00:00Z")])
        gone = await client.request("DELETE", "/auth/me", json={"confirm": "DELETE", "password": "password123"}, headers=_auth(first))
        assert gone.status_code == 204, gone.text

        assert (await client.post(f"/students/{sid}/bucket3/reprocess", headers=_auth(second))).status_code == 200
        assert "si:900030" in await _items(sid)
