"""Bug sweep leads (2026-10-24) in the Kids View and class pages: a grade's
class name blanked once the Classroom captures that named it are gone (L24),
and a class payment tick written read-then-write (L25)."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

import database
from main import app
from models import Bucket3Capture, ChildCourseGrade, ChildGradeEntry, User
from services.class_years import current_grad_years
from tests.test_kids_api import FEED_URL, _auth, _env, _family, _import, _load, _register
from tests.test_kids_lows import GRADES_URL

pytestmark = pytest.mark.anyio


def _client() -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_a_grade_keeps_its_class_name_once_the_classroom_pages_are_gone():
    async with _client() as client:
        _run, guardian, sid = await _family(client)
        await _import(
            client, guardian, sid,
            [_env("classroom", FEED_URL, _load("classroom_stream_feed.txt")), _env("genesis", GRADES_URL, _load("genesis_course_grades.txt"))],
        )
        # A co-guardian deleted their account, and the Classroom captures with it.
        async with database.SessionLocal() as db:
            await db.execute(delete(Bucket3Capture).where(Bucket3Capture.student_id == sid, Bucket3Capture.adapter == "classroom"))
            await db.commit()
        assert (await client.post(f"/students/{sid}/bucket3/reprocess", headers=_auth(guardian))).status_code == 200

        async with database.SessionLocal() as db:
            names = set((await db.execute(select(ChildGradeEntry.course_name).where(ChildGradeEntry.student_id == sid))).scalars())
            names |= set((await db.execute(select(ChildCourseGrade.course_name).where(ChildCourseGrade.student_id == sid))).scalars())
        assert names == {"ALGEBRA I 101-1"}


async def test_a_payment_tick_toggles_through_single_statements():
    async with _client() as client:
        email = f"tick_{uuid.uuid4().hex[:8]}@example.com"
        token = await _register(client, email)
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
        school = await client.post("/schools", json={"name": f"Tick High {uuid.uuid4().hex[:6]}", "school_type": "high"}, headers=_auth(token))
        base = f"/schools/{school.json()['id']}/class-years/{current_grad_years()[0]}"
        assert (await client.get(base)).status_code == 200
        payment = await client.post(f"{base}/payments", json={"sequence": 1, "kind": "optional", "label": "Prom"}, headers=_auth(token))
        assert payment.status_code == 201, payment.text

        ticks = [(await client.post(f"{base}/payments/{payment.json()['id']}/tick", headers=_auth(token))).json()["ticked"] for _ in range(3)]
        assert ticks == [True, False, True]
