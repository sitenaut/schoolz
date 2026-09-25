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
    def __init__(self, name, reply):
        self.name, self.reply = name, reply

    async def complete(self, model, **_):
        return Completion(content=[{"type": "text", "text": f"{self.reply} ({model})"}], usage=Usage(input_tokens=1_000_000, output_tokens=0))

    async def list_models(self):
        return ["m-1", "m-2"]


@pytest.mark.anyio
async def test_admin_settings_and_compare(monkeypatch):
    fakes = {"anthropic": _FakeProvider("anthropic", "claude says"), "gemini": _FakeProvider("gemini", "gemini says")}
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

        assert (await client.get("/admin/chatbot/models", params={"provider": "gemini"}, headers=_auth(admin))).json() == ["m-1", "m-2"]

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
