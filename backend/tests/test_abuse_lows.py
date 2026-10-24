"""Bug sweep 2026-10-23 lows: device-flow caps per connection, the MCP
submit tool's rate-limit bucket, class pages a crawler can create, a
first-sign-in race, and how much chat history reaches the model."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from starlette.applications import Starlette
from starlette.responses import PlainTextResponse
from starlette.routing import Route

import auth
import database
import mcp_server
from main import app
from models import SchoolClassYear, SubmissionAttempt, User
from request_context import RequestIdMiddleware, caller_ip_var
from routers import admin_api_keys, capture_devices
from services.chatbot import MAX_HISTORY_CHARS, trim_history
from services.class_years import current_grad_years
from tests.test_students import _make_admin, _register, _unique

pytestmark = pytest.mark.anyio


def _client(ip: str = "127.0.0.1") -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app, client=(ip, 0)), base_url="http://test")


@pytest.mark.parametrize(
    ("path", "per_ip"),
    [
        ("/auth/device/start", admin_api_keys.MAX_PENDING_DEVICE_REQUESTS_PER_IP),
        ("/capture-devices/start", capture_devices.MAX_PENDING_REQUESTS_PER_IP),
    ],
)
async def test_one_connection_cannot_fill_the_device_flow_queue(path, per_ip):
    async with _client("198.51.100.7") as flooder, _client("198.51.100.8") as someone_else:
        for _ in range(per_ip):
            assert (await flooder.post(path, json={"client_name": "flood"})).status_code == 200
        assert (await flooder.post(path, json={"client_name": "flood"})).status_code == 429
        assert (await someone_else.post(path, json={"client_name": "real"})).status_code == 200


async def test_capture_connect_keeps_a_code_not_the_address():
    from models import CaptureDeviceRequest

    async with _client("198.51.100.9") as client:
        started = (await client.post("/capture-devices/start", json={"client_name": "Backpack Capture"})).json()
    async with database.SessionLocal() as db:
        row = (await db.execute(select(CaptureDeviceRequest).where(CaptureDeviceRequest.user_code == started["user_code"]))).scalar_one()
    assert row.requester_ip_hash == capture_devices.requester_ip_hash("198.51.100.9")
    assert "198.51.100.9" not in row.requester_ip_hash


async def test_the_middleware_hands_the_callers_address_to_code_without_the_request():
    async def show(request):
        return PlainTextResponse(caller_ip_var.get() or "none")

    probe = RequestIdMiddleware(Starlette(routes=[Route("/", show)]))
    async with AsyncClient(transport=ASGITransport(app=probe, client=("192.0.2.44", 0)), base_url="http://t") as client:
        assert (await client.get("/")).text == "192.0.2.44"


async def test_mcp_submissions_are_limited_and_recorded_per_caller(monkeypatch):
    async def live(_client, _url):
        return None

    monkeypatch.setattr(mcp_server, "check_public_page", live)
    mcp = app.state.mcp
    url = f"https://example.com/handbook-{uuid.uuid4().hex[:8]}"
    token = caller_ip_var.set("203.0.113.9")
    try:
        await mcp.call_tool("submit_community_content", {"url": url, "description": "A handbook"})
    finally:
        caller_ip_var.reset(token)
    async with database.SessionLocal() as db:
        ips = (await db.execute(select(SubmissionAttempt.ip).where(SubmissionAttempt.url == url))).scalars().all()
    assert ips == ["203.0.113.9"]


async def _high_school(client: AsyncClient, school_type: str = "high") -> str:
    email = f"cy_{uuid.uuid4().hex[:8]}@example.com"
    headers = {"Authorization": f"Bearer {await _register(client, email, _unique('cy'))}"}
    await _make_admin(email)
    school = await client.post(
        "/schools", json={"name": f"Class Year School {uuid.uuid4().hex[:6]}", "school_type": school_type}, headers=headers
    )
    assert school.status_code == 201, school.text
    return school.json()["id"]


async def test_a_public_class_page_only_creates_rows_near_the_enrolled_classes():
    async with _client() as client:
        high = await _high_school(client)
        elementary = await _high_school(client, "elementary")
        seniors = current_grad_years()[0]

        assert (await client.get(f"/schools/{high}/class-years/{seniors - 2}")).status_code == 200
        for far in (1, seniors + 40, 99_999_999_999):
            assert (await client.get(f"/schools/{high}/class-years/{far}")).status_code == 404
            assert (await client.get(f"/schools/{high}/class-years/{far}/payments")).status_code == 404
        assert (await client.get(f"/schools/{elementary}/class-years/{seniors}")).status_code == 404

    async with database.SessionLocal() as db:
        years = (await db.execute(select(SchoolClassYear.grad_year).where(SchoolClassYear.school_id.in_([high, elementary])))).scalars().all()
    assert years == [seniors - 2]


async def test_a_class_year_someone_else_just_created_is_reused_not_a_500():
    from services.class_years import _insert_if_missing, get_or_create_class_year

    async with _client() as client:
        high = await _high_school(client)
    year = current_grad_years()[0]
    async with database.SessionLocal() as db:
        # Both of two simultaneous first visits get as far as the insert.
        await _insert_if_missing(db, high, year)
        await _insert_if_missing(db, high, year)
        row = await get_or_create_class_year(db, high, year)
        count = (
            await db.execute(select(func.count()).select_from(SchoolClassYear).where(SchoolClassYear.school_id == high))
        ).scalar_one()
    assert row.grad_year == year and count == 1


async def test_a_first_sign_in_that_loses_the_race_gets_the_winners_row(monkeypatch):
    sub = str(uuid.uuid4())
    email = f"race_{sub[:8]}@example.com"
    async with database.SessionLocal() as db:
        db.add(User(email=email, username=f"race_{sub[:8]}", supabase_user_id=sub))
        await db.commit()

    real_find = auth._find_supabase_user
    calls = []

    async def miss_first(db, supabase_user_id, mail):
        # The first lookup ran before the other request committed.
        calls.append(supabase_user_id)
        return None if len(calls) == 1 else await real_find(db, supabase_user_id, mail)

    monkeypatch.setattr(auth, "_find_supabase_user", miss_first)
    async with database.SessionLocal() as db:
        user = await auth._get_or_create_supabase_user(db, {"sub": sub, "email": email})
        count = (await db.execute(select(func.count()).select_from(User).where(User.supabase_user_id == sub))).scalar_one()
    assert user.email == email and count == 1 and len(calls) == 2


def _turn(n: int, size: int) -> list[dict]:
    return [
        {"role": "user", "content": f"question {n}"},
        {"role": "assistant", "content": [{"type": "text", "text": "x" * size}]},
    ]


def test_history_is_cut_to_a_size_as_well_as_a_count():
    history = [m for n in range(3) for m in _turn(n, MAX_HISTORY_CHARS // 2)]
    trimmed = trim_history(history)
    assert trimmed == _turn(2, MAX_HISTORY_CHARS // 2)
    assert trim_history(_turn(0, MAX_HISTORY_CHARS * 2)) == []
    small = [m for n in range(3) for m in _turn(n, 100)]
    assert trim_history(small) == small
