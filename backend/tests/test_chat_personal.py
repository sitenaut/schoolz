"""The chatbot's personal tools (services/chatbot_personal.py) and the
/chat endpoint's decision to offer them only to a signed-in caller."""
import json
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from routers import chat as chat_router
from services.chatbot_personal import PersonalTools
from tests.test_kids_api import _auth, _family, _register


@pytest.mark.anyio
async def test_personal_tools_see_only_the_callers_own_children():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        _run, guardian, sid = await _family(client)
        _run2, _other_guardian, other_sid = await _family(client, student_id="7654321", first_name="Other")

    tools = PersonalTools(app, guardian)
    try:
        children = json.loads(await tools.run("list_my_children", {}))
        assert [c["id"] for c in children["items"]] == [sid]

        todo = json.loads(await tools.run("get_child_todo", {"student_id": sid}))
        assert "missing" in todo and "error" not in todo

        # Another family's child is refused by the route's own ownership check.
        foreign = json.loads(await tools.run("get_child_todo", {"student_id": other_sid}))
        assert foreign["error"].startswith("404")

        # A model-built path fragment never reaches a URL.
        bad = json.loads(await tools.run("get_child_todo", {"student_id": "../notifications"}))
        assert "list_my_children" in bad["error"]
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_student_account_sees_itself():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        run, guardian, sid = await _family(client)
        kid_email = f"chatkid_{run}@example.com"
        invite = await client.post(
            f"/students/{sid}/account-invites", json={"invitee_email": kid_email}, headers=_auth(guardian)
        )
        kid = await _register(client, kid_email)
        accepted = await client.post(f"/student-account-invites/{invite.json()['token']}/accept", headers=_auth(kid))
        assert accepted.status_code == 200, accepted.text

    tools = PersonalTools(app, kid)
    try:
        children = json.loads(await tools.run("list_my_children", {}))
        assert [c["id"] for c in children["items"]] == [sid]
        assert "error" not in json.loads(await tools.run("get_child_schedule", {"student_id": sid}))
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_chat_offers_personal_tools_only_when_signed_in(monkeypatch):
    seen = []

    async def fake_turn(mcp, history, message, already_escalated, personal=None, config=None):
        seen.append(personal)
        return {"reply": "ok", "model": None, "history": [], "escalated": False}

    monkeypatch.setattr(chat_router, "run_chat_turn", fake_turn)
    monkeypatch.setattr(chat_router, "_requests_by_ip", chat_router.defaultdict(chat_router.deque))

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register(client, f"chat_{uuid.uuid4().hex[:8]}@example.com")
        assert (await client.post("/chat", json={"message": "hi"})).status_code == 200
        assert (await client.post("/chat", json={"message": "hi"}, headers=_auth("not-a-token"))).status_code == 200
        assert (await client.post("/chat", json={"message": "hi"}, headers=_auth(token))).status_code == 200

    assert seen[0] is None
    assert seen[1] is None  # a bad token degrades to public, never 401s
    assert isinstance(seen[2], PersonalTools)


@pytest.mark.anyio
async def test_find_local_events_keeps_only_free_classes_and_spreads_days():
    from datetime import datetime, timezone

    import database
    from models import LocalEvent

    src = f"chat_{uuid.uuid4().hex[:8]}"

    def utc(day, hour):  # 2031-06-07 (Sat) / 08 (Sun); hour in UTC, EDT = UTC-4
        return datetime(2031, 6, day, hour, tzinfo=timezone.utc)

    async with database.SessionLocal() as db:
        # Saturday alone overflows the 40-event cap.
        for i in range(60):
            db.add(LocalEvent(source=src, source_event_id=f"sat{i}", title=f"Sat thing {i}", start_time=utc(7, 14), categories=["music"]))
        db.add(LocalEvent(source=src, source_event_id="sun", title="Sunday pumpkin patch", start_time=utc(8, 15),
                          categories=["outdoor"], is_free=True, description="Hayrides for kids"))
        # Classes: paid/unknown ones are dropped, explicitly free ones kept.
        db.add(LocalEvent(source=src, source_event_id="gym", title="Open Gym", start_time=utc(8, 12), categories=["ymca", "open-gym"]))
        db.add(LocalEvent(source=src, source_event_id="pottery", title="Kids Pottery Class", start_time=utc(8, 13), categories=["arts"],
                          description="Gluten-free snacks provided. Feel free to bring a friend."))
        db.add(LocalEvent(source=src, source_event_id="yoga", title="Family Yoga Workshop", start_time=utc(8, 14), categories=["fitness"],
                          description="Complimentary for residents."))
        db.add(LocalEvent(source=src, source_event_id="swim", title="Aqua Fit", start_time=utc(8, 16), categories=["ymca", "pool"], is_free=True))
        # 01:00 UTC Monday is still Sunday evening locally - inside the range.
        db.add(LocalEvent(source=src, source_event_id="late", title="Sunday evening story time", start_time=utc(9, 1), categories=["library", "kids"]))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register(client, f"chatlocal_{uuid.uuid4().hex[:8]}@example.com")

    tools = PersonalTools(app, token)
    try:
        res = json.loads(await tools.run("find_local_events", {"start_date": "2031-06-07", "end_date": "2031-06-08"}))
        titles = [e["title"] for e in res["items"]]
        assert res["matched"] == 64 and res["returned"] == 40 and "note" in res
        assert "Open Gym" not in titles and "Kids Pottery Class" not in titles  # no sign it's free
        assert "Family Yoga Workshop" in titles and "Aqua Fit" in titles  # explicitly free
        assert "Sunday pumpkin patch" in titles and "Sunday evening story time" in titles  # ...and Sunday survives the cap
        patch = next(e for e in res["items"] if e["title"] == "Sunday pumpkin patch")
        assert patch["when"] == "Sun Jun 8 11:00 AM" and patch["price"] == "free"

        # Asking for classes by category still never surfaces a paid one.
        gym = json.loads(await tools.run("find_local_events", {"start_date": "2031-06-08", "end_date": "2031-06-08", "categories": "ymca,open-gym"}))
        assert [e["title"] for e in gym["items"]] == ["Aqua Fit"]

        bad = json.loads(await tools.run("find_local_events", {"start_date": "this weekend", "end_date": "2031-06-08"}))
        assert "YYYY-MM-DD" in bad["error"]
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_category_list_is_live_sorted_and_cached(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import database
    from models import LocalEvent
    from services import chatbot_personal

    monkeypatch.setattr(chatbot_personal, "_category_cache", {"text": None, "at": 0.0})
    monkeypatch.setattr(chatbot_personal, "_MAX_CATEGORIES", 10_000)  # the dev DB has real tags too
    src = f"chatcat_{uuid.uuid4().hex[:8]}"
    soon = datetime.now(timezone.utc) + timedelta(days=2)
    async with database.SessionLocal() as db:
        for i in range(3):
            db.add(LocalEvent(source=src, source_event_id=f"z{i}", title="z", start_time=soon, categories=["zzz-test-tag"]))
        db.add(LocalEvent(source=src, source_event_id="once", title="once", start_time=soon, categories=["one-off-tag"]))
        await db.commit()

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register(client, f"chatcat_{uuid.uuid4().hex[:8]}@example.com")

    tools = PersonalTools(app, token)
    try:
        first = {t["name"]: t["description"] for t in await tools.tool_defs()}["find_local_events"]
        listed = first.split("Categories in use: ")[1].split(". ")[0].split(", ")
        assert "zzz-test-tag" in listed and "one-off-tag" not in listed  # below the 3-event floor
        assert listed == sorted(listed)

        # Within the hour the description is byte-identical, even if the data moves.
        async with database.SessionLocal() as db:
            for i in range(5):
                db.add(LocalEvent(source=src, source_event_id=f"n{i}", title="n", start_time=soon, categories=["new-tag"]))
            await db.commit()
        second = {t["name"]: t["description"] for t in await tools.tool_defs()}["find_local_events"]
        assert second == first
    finally:
        await tools.aclose()


@pytest.mark.anyio
async def test_routine_class_tags_stay_out_of_the_category_list(monkeypatch):
    from datetime import datetime, timedelta, timezone

    import database
    from models import LocalEvent
    from services import chatbot_personal

    monkeypatch.setattr(chatbot_personal, "_category_cache", {"text": None, "at": 0.0})
    monkeypatch.setattr(chatbot_personal, "_MAX_CATEGORIES", 10_000)
    src = f"chaty_{uuid.uuid4().hex[:8]}"
    soon = datetime.now(timezone.utc) + timedelta(days=1)
    async with database.SessionLocal() as db:
        for i in range(5):
            db.add(LocalEvent(source=src, source_event_id=f"y{i}", title="Aqua Fit", start_time=soon, categories=["ymca", "pool"]))
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        token = await _register(client, f"chaty_{uuid.uuid4().hex[:8]}@example.com")
    tools = PersonalTools(app, token)
    try:
        listed = (await tools._category_list()).split(", ")
        assert "ymca" not in listed and "pool" not in listed
    finally:
        await tools.aclose()
