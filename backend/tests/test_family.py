"""My family (routers/family.py): what schoolz can bring in for each child,
and how much has arrived."""
import os
import uuid
from datetime import datetime
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import update

import database
from main import app
from models import User
from routers import bucket3 as bucket3_router

ET = ZoneInfo("America/New_York")
FIXTURES = os.path.join(os.path.dirname(__file__), "fixtures", "bucket3")
SID = "1234567"  # the Classroom fixture's login is 1234567@example.org
FEED_URL = "https://classroom.google.com/u/2/w/AAAASLUG/t/all"
GENESIS = "https://parents.example.org/genesis/parents"


def _load(name: str) -> str:
    with open(os.path.join(FIXTURES, name), encoding="utf-8") as f:
        return f.read()


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _env(adapter: str, url: str, text: str) -> dict:
    return {"adapter": adapter, "source_url": url, "reduced_text": text, "captured_at": "2026-09-14T11:00:00Z", "status": "ok", "char_count": len(text)}


async def _register(client: AsyncClient, email: str, admin: bool = False) -> str:
    res = await client.post("/auth/register", json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"})
    assert res.status_code == 201, res.text
    if admin:
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            await db.commit()
    return res.json()["access_token"]


async def _district(client: AsyncClient, token: str, **settings) -> dict:
    res = await client.post("/districts", json={"name": f"Family Test District {uuid.uuid4().hex[:8]}", **settings}, headers=_auth(token))
    assert res.status_code == 201, res.text
    return res.json()


async def _child(client: AsyncClient, token: str, first: str, student_id: str, district_id: str | None) -> str:
    body = {"name": f"Family Test School {uuid.uuid4().hex[:8]}", "school_type": "high"}
    if district_id:
        body["district_id"] = district_id
    school = await client.post("/schools", json=body, headers=_auth(token))
    assert school.status_code == 201, school.text
    res = await client.post(
        "/students",
        json={"first_name": first, "last_name": "Family", "student_id": student_id, "school_id": school.json()["id"]},
        headers=_auth(token),
    )
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.anyio
async def test_homework_and_grades_are_offered_only_where_the_district_has_them():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        parent = await _register(client, f"fam_{uuid.uuid4().hex[:8]}@example.com", admin=True)
        both = await _district(client, parent, uses_google_classroom=True, genesis_url=GENESIS)
        neither = await _district(client, parent)
        assert both["uses_google_classroom"] is True and both["genesis_url"] == GENESIS
        a = await _child(client, parent, "Avery", f"9{uuid.uuid4().int % 10**6:06d}", both["id"])
        b = await _child(client, parent, "Blake", f"8{uuid.uuid4().int % 10**6:06d}", neither["id"])

        kids = {k["id"]: k for k in (await client.get("/family", headers=_auth(parent))).json()}
        assert [kids[a]["has_classroom"], kids[a]["has_genesis"]] == [True, True]
        assert [kids[b]["has_classroom"], kids[b]["has_genesis"]] == [False, False]
        assert kids[a]["district_name"] == both["name"]
        # Nothing has arrived: counts are unknown, not zero.
        assert [kids[a]["due_this_week"], kids[a]["missing"], kids[a]["classes"], kids[a]["today"]] == [None, None, None, None]
        assert kids[a]["guardian_count"] == 1 and kids[a]["specials_count"] == 0

        # Switching a district on (and Genesis off again) shows straight away.
        res = await client.patch(f"/districts/{neither['id']}", json={"uses_google_classroom": True}, headers=_auth(parent))
        assert res.status_code == 200, res.text
        res = await client.patch(f"/districts/{both['id']}", json={"genesis_url": ""}, headers=_auth(parent))
        assert res.json()["genesis_url"] is None
        kids = {k["id"]: k for k in (await client.get("/family", headers=_auth(parent))).json()}
        assert kids[b]["has_classroom"] is True
        assert kids[a]["has_genesis"] is False

        # Only the caller's own children; a guardian with none gets an empty list.
        stranger = await _register(client, f"fam_other_{uuid.uuid4().hex[:8]}@example.com")
        assert (await client.get("/family", headers=_auth(stranger))).json() == []


@pytest.mark.anyio
async def test_counts_and_today_once_data_arrives(monkeypatch):
    monkeypatch.setattr(bucket3_router, "_local_now", lambda: datetime(2026, 9, 14, 8, 0, tzinfo=ET))
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        parent = await _register(client, f"fam_{uuid.uuid4().hex[:8]}@example.com", admin=True)
        # No district settings at all: data that arrived is enough.
        sid = await _child(client, parent, "Casey", SID, None)
        daily = f"{GENESIS}?tab1=studentdata&tab2=studentsummary&studentid={SID}"
        grades = f"{GENESIS}?tab1=studentdata&tab2=gradebook&tab3=coursesummary&studentid={SID}&courseCode=101&courseSection=1"
        res = await client.post(
            f"/students/{sid}/bucket3/import",
            json={
                "captures": [
                    _env("classroom", FEED_URL, _load("classroom_stream_feed.txt")),
                    _env("genesis", daily, _load("genesis_daily_view.txt").replace("9999999", SID)),
                    _env("genesis", grades, _load("genesis_course_grades.txt")),
                ]
            },
            headers=_auth(parent),
        )
        assert res.status_code == 200, res.text

        [kid] = (await client.get("/family", headers=_auth(parent))).json()
        assert kid["has_classroom"] is True and kid["has_genesis"] is True
        assert kid["classroom_seen_at"] and kid["genesis_seen_at"]
        # The lab contract is due 9/18, inside this week; the pre-test is done.
        assert kid["due_this_week"] == 1
        assert kid["missing"] == 0
        assert kid["classes"] == 1
        assert kid["today"] == {"state": "now", "course_name": "GEOMETRY A", "room": kid["today"]["room"], "time_start": kid["today"]["time_start"], "time_end": kid["today"]["time_end"]}

        # A day with no schedule captured shows no schedule line at all.
        monkeypatch.setattr(bucket3_router, "_local_now", lambda: datetime(2026, 9, 15, 8, 0, tzinfo=ET))
        [kid] = (await client.get("/family", headers=_auth(parent))).json()
        assert kid["today"] is None

        # A pending login invite for the child is named until it's accepted.
        kid_email = f"fam_kid_{uuid.uuid4().hex[:8]}@example.com"
        invite = await client.post(f"/students/{sid}/account-invites", json={"invitee_email": kid_email}, headers=_auth(parent))
        [kid] = (await client.get("/family", headers=_auth(parent))).json()
        assert kid["student_invite_email"] == kid_email and kid["student_login_email"] is None
        child_token = await _register(client, kid_email)
        await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(child_token))
        [kid] = (await client.get("/family", headers=_auth(parent))).json()
        assert kid["student_login_email"] == kid_email and kid["student_invite_email"] is None


@pytest.mark.anyio
async def test_a_seed_without_the_settings_leaves_them_alone():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _register(client, f"fam_{uuid.uuid4().hex[:8]}@example.com", admin=True)
        name = f"Family Seed District {uuid.uuid4().hex[:8]}"
        district = {
            "name": name,
            "website_url": None,
            "food_services_menu_url": None,
            "ics_feeds": [],
            "marking_period_url": None,
            "preschool_locations_url": None,
            "preschool_team_url": None,
            "hs_rotation_url": None,
            "transportation_url": None,
        }

        def payload(d: dict) -> dict:
            return {"exported_at": "2026-10-21T00:00:00Z", "source": "test", "districts": [d], "schools": [], "smore_newsletters": []}

        async def settings() -> tuple:
            row = next(d for d in (await client.get("/districts")).json() if d["name"] == name)
            return row["uses_google_classroom"], row["genesis_url"]

        res = await client.post("/admin/config/import", json=payload({**district, "uses_google_classroom": True, "genesis_url": GENESIS}), headers=_auth(admin))
        assert res.status_code == 200, res.text
        assert await settings() == (True, GENESIS)
        # An older seed file that predates the settings doesn't switch them off.
        res = await client.post("/admin/config/import", json=payload(district), headers=_auth(admin))
        assert res.status_code == 200, res.text
        assert await settings() == (True, GENESIS)
