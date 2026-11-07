"""What a chat turn sends the model, kept small. Nearly all of the chat's
spend on prod was Sonnet writing whole conversations into its cache: a
question switched to it after Haiku's lookups had already pulled in tool
results of up to 184k characters."""
import json
import os
import uuid
from datetime import date, timedelta

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest

import database
from main import app
from models import School, SeasonalAttraction, StaffMember
from services.chat_providers import Completion, Usage
from services.chat_settings import AudienceConfig
from services.chatbot import MAX_TOOL_RESULT_CHARS, _run_tool, fit_tool_result, run_chat_turn


class _TwoLookups:
    """Two tool rounds, then an answer, noting the model of every call."""

    def __init__(self):
        self.models = []

    async def complete(self, model, messages, **_):
        self.models.append(model)
        if len(self.models) <= 2:
            return Completion(content=[{"type": "tool_use", "id": f"t{len(self.models)}", "name": "list_schools", "input": {}}],
                              usage=Usage())
        return Completion(content=[{"type": "text", "text": "Here you go."}], usage=Usage())


@pytest.mark.anyio
async def test_escalation_is_decided_before_the_first_call():
    config = AudienceConfig(model="claude-haiku-5-5", escalation_model="claude-sonnet-5-5")

    async def turn(message, already_escalated=False):
        provider = _TwoLookups()
        result = await run_chat_turn(app.state.mcp, history=[], message=message, already_escalated=already_escalated,
                                     config=config, providers={"anthropic": provider})
        return provider.models, result["escalated"]

    # Two lookups no longer hand the answer to Sonnet partway through.
    assert await turn("what's for lunch at bret harte") == (["claude-haiku-5-5"] * 3, False)
    # A compound question goes to Sonnet from its first call...
    assert await turn("compare East and West or Rosa lunch") == (["claude-sonnet-5-5"] * 3, True)
    # ...and so does the rest of its conversation.
    assert await turn("and tomorrow?", already_escalated=True) == (["claude-sonnet-5-5"] * 3, True)


def test_a_long_tool_result_keeps_whole_items_and_says_how_to_narrow():
    rows = [{"title": f"Event {n}", "description": "x" * 400} for n in range(200)]
    pretty = json.dumps({"count": 200, "items": rows}, indent=2)  # as the MCP server writes it
    fitted = fit_tool_result(pretty, ["q", "start", "end"])
    data = json.loads(fitted)  # still JSON: no item was cut in half
    shown = len(data["items"])
    assert len(fitted) <= MAX_TOOL_RESULT_CHARS
    assert 0 < shown < 200 and data["items"] == rows[:shown]  # the first ones, in order
    assert data["truncated"] == f"Only the first {shown} of 200 items are shown: call again with q or start or end to narrow it."

    # Nothing narrows it: the model is told the list goes on.
    assert "say there are more" in json.loads(fit_tool_result(pretty, []))["truncated"]

    # A short result only loses the indenting.
    small = {"count": 1, "items": [{"title": "Fair", "note": None}]}
    assert fit_tool_result(json.dumps(small, indent=2), ["q"]) == '{"count":1,"items":[{"title":"Fair","note":null}]}'

    # Text that isn't a list result is cut.
    words = "word " * 10_000
    cut = fit_tool_result(words, [])
    assert cut.startswith(words[:MAX_TOOL_RESULT_CHARS]) and cut.endswith("narrower question]\"")


@pytest.mark.anyio
async def test_seasonal_attractions_come_back_compact_and_within_the_chat_cap():
    season = f"test-{uuid.uuid4().hex[:8]}"
    d0 = date(2031, 11, 1)  # far from the seeded seasons, so only this test's rows match
    async with database.SessionLocal() as db:
        db.add_all([
            SeasonalAttraction(
                season=season, kind="light_show", name=f"Lights {n:03}", address="1 Main St, Somewhere, NJ",
                town="Somewhere", latitude=39.9, longitude=-75.0, url="https://example.com/",
                starts_on=d0 - timedelta(days=10), ends_on=d0 + timedelta(days=40),
                open_dates=[d0 + timedelta(days=k) for k in range(-10, 40)],
                note="A drive-through light show. " * 20, source_url="https://example.com/checked", verified_on=d0,
            )
            for n in range(80)
        ])
        await db.commit()

    raw = await _run_tool(app.state.mcp, "find_seasonal_attractions", {"season": season, "on_date": d0.isoformat()})
    data = json.loads(raw)
    assert data["matched"] == 80 and 0 < data["returned"] == len(data["items"]) < 80
    assert "narrow by kind" in data["more"]
    # Small enough on its own that the chat never has to cut it.
    assert "truncated" not in json.loads(fit_tool_result(raw, ["kind"]))

    first = data["items"][0]
    assert first["name"] == "Lights 000"
    assert not {"id", "latitude", "longitude", "source_url", "verified_on", "resource_id", "miles"} & set(first)
    assert first["open_dates"] == [(d0 + timedelta(days=k)).isoformat() for k in range(6)]  # the next few nights
    assert len(first["note"]) == 240
    assert first["scare_level"] is None and first["open_on_day"] is True  # null is an answer, so it stays


@pytest.mark.anyio
async def test_staff_role_holders_come_first():
    # The chat keeps the start of a long directory: by name alone, a big
    # school's nurse could be past the cut.
    slug = f"staffcap-{uuid.uuid4().hex[:8]}"
    async with database.SessionLocal() as db:
        school = School(name=f"Staffcap Elementary {slug}", slug=slug, school_type="elementary")
        db.add(school)
        await db.flush()
        db.add_all([
            StaffMember(school_id=school.id, source_constituent_id="1", full_name="Aaron Able", title="Teacher"),
            StaffMember(school_id=school.id, source_constituent_id="2", full_name="Zelda Zimmer", title="School Nurse", role="nurse"),
            StaffMember(school_id=school.id, source_constituent_id="3", full_name="Ben Baker", title="Teacher"),
            StaffMember(school_id=school.id, source_constituent_id="4", full_name="Mia Mock", title="Principal", role="principal"),
        ])
        await db.commit()

    data = json.loads(await _run_tool(app.state.mcp, "list_school_staff", {"school_id_or_slug": slug}))
    assert [s["full_name"] for s in data["items"]] == ["Mia Mock", "Zelda Zimmer", "Aaron Able", "Ben Baker"]
