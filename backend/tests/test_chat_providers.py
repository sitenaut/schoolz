"""The chatbot's provider layer (services/chat_providers.py) and the admin
controls around it (routers/admin_chatbot.py)."""
import json
import os
import uuid
from functools import partial

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

from main import app
from routers import admin_chatbot
from services import chat_providers, chat_settings
from services.chat_providers import Completion, OpenAICompatibleProvider, Usage, _gemini_schema
from services.chat_settings import AudienceConfig
from services.chatbot import run_chat_turn
from tests.test_kids_api import _register
from tests.test_students import _make_admin


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def test_gemini_schema_drops_unsupported_keywords():
    schema = {
        "type": "object",
        "title": "submit_community_contentArguments",
        "properties": {
            "url": {"type": "string", "title": "Url"},
            "school_id_or_slug": {"anyOf": [{"type": "string"}, {"type": "null"}], "default": None, "title": "School"},
        },
        "required": ["url"],
        "additionalProperties": False,
    }
    assert _gemini_schema(schema) == {
        "type": "object",
        "properties": {"url": {"type": "string"}, "school_id_or_slug": {"type": "string"}},
        "required": ["url"],
    }


@pytest.mark.anyio
async def test_openai_compatible_round_trip_through_the_agent_loop(monkeypatch):
    """A Gemini-style tool call, the tool result sent back as a role:tool
    message, the provider's extra call fields echoed verbatim, then text."""
    requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = json.loads(request.content)
        requests.append(body)
        if len(requests) == 1:
            message = {"role": "assistant", "content": None, "tool_calls": [{
                "id": "call.1", "type": "function",
                "function": {"name": "list_schools", "arguments": "{}"},
                "extra_content": {"google": {"thought_signature": "SIG123"}},
            }]}
        else:
            message = {"role": "assistant", "content": "There are schools."}
        return httpx.Response(200, json={
            "choices": [{"message": message}],
            "usage": {"prompt_tokens": 1000, "completion_tokens": 20, "prompt_tokens_details": {"cached_tokens": 600}},
        })

    monkeypatch.setattr(chat_providers.httpx, "AsyncClient", partial(httpx.AsyncClient, transport=httpx.MockTransport(handler)))
    provider = OpenAICompatibleProvider("gemini", "https://gemini.test/v1beta/openai", "key", schema_fixer=_gemini_schema)
    config = AudienceConfig(provider="gemini", model="gemini-test-flash", escalation_model=None, reasoning_effort="low")

    result = await run_chat_turn(app.state.mcp, history=[], message="Which schools are there?", already_escalated=False,
                                 config=config, providers={"gemini": provider})

    assert result["reply"] == "There are schools."
    assert result["tools_called"] == ["list_schools"] and result["model"] == "gemini-test-flash"
    first, second = requests
    assert first["model"] == "gemini-test-flash" and first["reasoning_effort"] == "low"
    assert first["messages"][0]["role"] == "system"
    assert all(t["type"] == "function" and "title" not in json.dumps(t["function"]["parameters"]) for t in first["tools"])
    # Round 2 replays the call (with its signature) and the tool result.
    assistant = second["messages"][-2]
    assert assistant["tool_calls"][0]["extra_content"] == {"google": {"thought_signature": "SIG123"}}
    tool_msg = second["messages"][-1]
    assert tool_msg["role"] == "tool" and tool_msg["tool_call_id"] == assistant["tool_calls"][0]["id"]
    # Ids are made Anthropic-safe so history survives a provider switch.
    assert "." not in assistant["tool_calls"][0]["id"]
    usage = result["usage_by_model"]["gemini-test-flash"]
    assert (usage.input_tokens, usage.cache_read_tokens, usage.output_tokens) == (800, 1200, 40)

    # History carries the private extra key; the Anthropic path must strip it.
    history_call = result["history"][1]["content"][0]
    assert history_call["_openai_extra"]["extra_content"]["google"]["thought_signature"] == "SIG123"
    assert chat_providers._strip_private([history_call])[0].keys() == {"type", "id", "name", "input"}


class _FakeProvider:
    def __init__(self, name, reply, models=("m-1", "m-2")):
        self.name, self.reply, self.models = name, reply, list(models)

    async def complete(self, model, **_):
        return Completion(content=[{"type": "text", "text": f"{self.reply} ({model})"}], usage=Usage(input_tokens=1_000_000, output_tokens=0))

    async def list_models(self):
        return self.models


@pytest.mark.anyio
async def test_admin_settings_and_compare(monkeypatch):
    fakes = {
        "anthropic": _FakeProvider("anthropic", "claude says", ["claude-haiku-4-5-20251001", "claude-sonnet-5"]),
        "gemini": _FakeProvider("gemini", "gemini says", ["gemini-x", "gemini-y"]),
    }
    monkeypatch.setattr(admin_chatbot, "configured_providers", lambda: fakes)
    monkeypatch.setattr(chat_settings, "_cache", {"value": None, "at": 0.0})

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        plain = await _register(client, f"chatplain_{uuid.uuid4().hex[:8]}@example.com")
        assert (await client.get("/admin/chatbot", headers=_auth(plain))).status_code == 403

        email = f"chatadmin_{uuid.uuid4().hex[:8]}@example.com"
        admin = await _register(client, email)
        await _make_admin(email)

        got = (await client.get("/admin/chatbot", headers=_auth(admin))).json()
        assert got["settings"]["anonymous"]["provider"] == "anthropic"
        assert {p["name"] for p in got["providers"] if p["configured"]} == {"anthropic", "gemini"}

        settings = got["settings"]
        settings["anonymous"] = {"provider": "gemini", "model": "gemini-x", "escalation_model": None, "reasoning_effort": "low"}
        settings["prices"]["gemini-x"] = {"input": 0.3, "output": 2.5, "cache_read": 0.03}
        saved = await client.put("/admin/chatbot", json=settings, headers=_auth(admin))
        assert saved.status_code == 200, saved.text
        assert (await chat_settings.get_settings(None)).anonymous.model == "gemini-x"  # served from the cache

        # A provider with no key on the server can't be made live.
        monkeypatch.setattr(admin_chatbot, "configured_providers", lambda: {"anthropic": fakes["anthropic"]})
        rejected = await client.put("/admin/chatbot", json=settings, headers=_auth(admin))
        assert rejected.status_code == 400 and "no API key" in rejected.json()["detail"]
        monkeypatch.setattr(admin_chatbot, "configured_providers", lambda: fakes)

        assert (await client.get("/admin/chatbot/models", params={"provider": "gemini"}, headers=_auth(admin))).json() == ["gemini-x", "gemini-y"]

        # The prod outage: a Claude escalation model saved under Gemini.
        settings["anonymous"]["escalation_model"] = "claude-sonnet-5"
        mismatched = await client.put("/admin/chatbot", json=settings, headers=_auth(admin))
        assert mismatched.status_code == 400 and "isn't a gemini model" in mismatched.json()["detail"]
        settings["anonymous"]["escalation_model"] = "gemini-y"
        assert (await client.put("/admin/chatbot", json=settings, headers=_auth(admin))).status_code == 200

        # With the provider's list unavailable, the prefix rule still catches it.
        async def down():
            raise httpx.ConnectError("down")

        monkeypatch.setattr(fakes["gemini"], "list_models", down)
        settings["anonymous"]["model"] = "claude-haiku-4-5-20251001"
        assert (await client.put("/admin/chatbot", json=settings, headers=_auth(admin))).status_code == 400
        settings["anonymous"]["model"] = "gemini-x"
        assert (await client.put("/admin/chatbot", json=settings, headers=_auth(admin))).status_code == 200

        compared = await client.post("/admin/chatbot/compare", headers=_auth(admin), json={
            "message": "hi",
            "configs": [
                {"provider": "anthropic", "model": "claude-haiku-4-5", "escalation_model": None},
                {"provider": "gemini", "model": "gemini-x", "escalation_model": None},
                {"provider": "gemini", "model": "gemini-unpriced", "escalation_model": None},
            ],
        })
        assert compared.status_code == 200, compared.text
        a, b, c = compared.json()
        assert a["reply"] == "claude says (claude-haiku-4-5)" and a["cost_usd"] == pytest.approx(1.0)  # 1M input at $1
        assert b["reply"] == "gemini says (gemini-x)" and b["cost_usd"] == pytest.approx(0.3)
        assert c["cost_usd"] is None  # no price on file: no guess


class _BrokenEscalation:
    """Tool call on the base model, then a 404 for the escalation model -
    what Gemini returned on prod for claude-sonnet-5."""

    name = "gemini"

    def __init__(self):
        self.models = []

    async def complete(self, model, messages, **_):
        self.models.append(model)
        if model == "claude-sonnet-5":
            raise RuntimeError("gemini returned 404: model not found")
        if len(self.models) == 1:
            return Completion(content=[{"type": "tool_use", "id": "t1", "name": "list_schools", "input": {}}], usage=Usage())
        return Completion(content=[{"type": "text", "text": "Here you go."}], usage=Usage())


@pytest.mark.anyio
async def test_a_failing_escalation_model_falls_back_to_the_base_model():
    provider = _BrokenEscalation()
    config = AudienceConfig(provider="gemini", model="gemini-x", escalation_model="claude-sonnet-5")
    # "compare ... and ... or" trips the escalation heuristic on the first tool round.
    result = await run_chat_turn(
        app.state.mcp, history=[], message="compare East and West or Rosa lunch", already_escalated=False,
        config=config, providers={"gemini": provider},
    )
    assert result["reply"] == "Here you go."
    assert provider.models == ["gemini-x", "claude-sonnet-5", "gemini-x"]
    assert result["escalated"] is False and result["model"] == "gemini-x"
    assert "404" in result["escalation_error"]

    # A client echoing escalated=true from an earlier turn falls back too.
    provider = _BrokenEscalation()
    provider.models = ["already-past-round-one"]
    result = await run_chat_turn(
        app.state.mcp, history=[], message="hi", already_escalated=True, config=config, providers={"gemini": provider},
    )
    assert result["reply"] == "Here you go." and result["escalated"] is False


def test_gemini_list_keeps_only_chat_models():
    ids = ["gemini-3.8-flash", "gemini-3.8-flash-tts", "gemini-3-pro-image", "gemini-embedding-2", "gemini-3.8-live",
           "gemini-2.5-flash-native-audio-latest", "gemma-4-31b-it", "veo-3.1-generate-preview", "gemini-pro-latest"]
    assert [i for i in ids if chat_providers.gemini_chat_model(i)] == ["gemini-3.8-flash", "gemini-pro-latest"]


@pytest.mark.anyio
async def test_anonymous_turns_are_told_todays_date():
    seen = {}

    class _Capture:
        name = "anthropic"

        async def complete(self, model, dynamic_system=None, **_):
            seen["dynamic_system"] = dynamic_system
            return Completion(content=[{"type": "text", "text": "ok"}], usage=Usage())

    await run_chat_turn(app.state.mcp, history=[], message="what's on next week?", already_escalated=False,
                        personal=None, config=AudienceConfig(escalation_model=None), providers={"anthropic": _Capture()})
    assert seen["dynamic_system"].startswith("Today is ")



@pytest.mark.anyio
async def test_calendar_tool_drops_rotation_markers_unless_asked():
    from datetime import datetime, timezone

    import database
    from models import District, School, SchoolContentItem
    from services.chatbot import _run_tool

    async with database.SessionLocal() as db:
        district = District(name="Rotation Test District")
        db.add(district)
        await db.flush()
        db.add(School(name="Rotation Test High", slug="rotation-test-high", school_type="high", district_id=district.id))
        common = dict(scope="district", district_id=district.id, category="event", is_current=True, source="ics_feed",
                      is_all_day=True, start_date=datetime(2026, 9, 29, 4, tzinfo=timezone.utc))
        db.add_all([SchoolContentItem(title=t, **common) for t in ("Day 2", "Day 5", "ROTTEST Senior Portraits", "Day 2 Field Trip")])
        await db.commit()

    args = {"start": "2026-09-29T00:00:00Z", "end": "2026-09-29T23:59:59Z", "school_ids": "rotation-test-high"}
    default = json.loads(await _run_tool(app.state.mcp, "list_calendar_items", args))
    titles = {i["title"] for i in default["items"]}
    assert "ROTTEST Senior Portraits" in titles and "Day 2 Field Trip" in titles
    assert not {"Day 2", "Day 5"} & titles
    asked = json.loads(await _run_tool(app.state.mcp, "list_calendar_items", {**args, "include_rotation_days": True}))
    assert {"Day 2", "Day 5"} <= {i["title"] for i in asked["items"]}
