import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import date, datetime

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import District, School, SchoolContentItem
from services.kids_schedule import upcoming_days
from services.school_today import LOCAL_TZ, build_today
from tests.test_students import _register


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _day(d: date) -> datetime:
    return datetime.combine(d, datetime.min.time(), LOCAL_TZ)


@pytest.mark.anyio
async def test_specials_shared_across_guardians_and_shown_on_today_and_schedule():
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Specials District {run}")
        db.add(district)
        await db.flush()
        school = School(name=f"Specials Elementary {run}", slug=f"specials-elem-{run}", school_type="elementary", district_id=district.id)
        db.add(school)
        await db.flush()
        common = dict(scope="district", district_id=district.id, category="event", is_current=True, is_all_day=True, source="ics_feed", applies_to_school_types=["elementary"])
        # Mon Oct 5 - Fri Oct 9 2026 = Day 1..5; a high-school-only Day 6 must not count.
        for n, d in enumerate([date(2026, 10, 5), date(2026, 10, 6), date(2026, 10, 7), date(2026, 10, 8), date(2026, 10, 9)], start=1):
            db.add(SchoolContentItem(title=f"Day {n}", start_date=_day(d), **common))
        db.add(SchoolContentItem(title="Day 6", start_date=_day(date(2026, 10, 5)), **{**common, "applies_to_school_types": ["high"]}))
        await db.commit()
        school_id, school_slug = school.id, school.slug

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        mom = await _register(client, f"mom_{run}@example.com", f"mom_{run}")
        dad = await _register(client, f"dad_{run}@example.com", f"dad_{run}")
        stranger = await _register(client, f"x_{run}@example.com", f"x_{run}")
        for token in (mom, dad):
            res = await client.post("/students", json={"first_name": "Zoe", "last_name": "Q", "student_id": f"s-{run}", "school_id": school_id}, headers=auth(token))
            assert res.status_code == 201, res.text
        student_id = res.json()["id"]
        assert res.json()["school_type"] == "elementary"

        empty = (await client.get(f"/students/{student_id}/specials", headers=auth(mom))).json()
        assert empty == {"rotation_days": [1, 2, 3, 4, 5], "specials": []}

        body = [
            {"rotation_day": 1, "subject": "Art"},
            {"rotation_day": 2, "subject": "PE", "teacher": "Mr. Gym"},
            {"rotation_day": 3, "subject": "  "},  # blank = unknown, not stored
        ]
        saved = (await client.put(f"/students/{student_id}/specials", json=body, headers=auth(mom))).json()
        assert [(s["rotation_day"], s["subject"]) for s in saved["specials"]] == [(1, "Art"), (2, "PE")]

        # Shared with the other guardian, invisible to anyone else.
        assert len((await client.get(f"/students/{student_id}/specials", headers=auth(dad))).json()["specials"]) == 2
        assert (await client.get(f"/students/{student_id}/specials", headers=auth(stranger))).status_code == 404
        dup = [{"rotation_day": 1, "subject": "Art"}, {"rotation_day": 1, "subject": "Music"}]
        assert (await client.put(f"/students/{student_id}/specials", json=dup, headers=auth(dad))).status_code == 400

        # Public Today stays anonymous; a guardian's gets their kid's specials.
        assert (await client.get(f"/schools/{school_slug}/today")).json()["my_specials"] == []

    async with database.SessionLocal() as db:
        school = await db.get(School, school_id)
        from models import User
        from sqlalchemy import select

        mom_id = (await db.execute(select(User.id).where(User.email == f"mom_{run}@example.com"))).scalar_one()
        today = await build_today(db, school, date(2026, 10, 5), user_id=mom_id)
        [kid] = today.my_specials
        assert (kid.first_name, kid.today, kid.next_label, kid.next) == ("Zoe", "Art", "Tomorrow", "PE")
        assert kid.by_date == {"2026-10-05": "Art", "2026-10-06": "PE"}

        days = await upcoming_days(db, school, student_id, date(2026, 10, 5), 3)
        assert [(d["rotation_day"], [b["course_name"] for b in d["blocks"]]) for d in days] == [("Day 1", ["Art"]), ("Day 2", ["PE"]), ("Day 3", [])]
