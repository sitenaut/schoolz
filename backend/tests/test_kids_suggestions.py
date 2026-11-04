"""The Kids view's on-demand calls on the shared Haiku settings. Haiku 5.5 400s
on a non-default temperature, so a request that still sends one breaks the
button rather than changing an answer."""
from types import SimpleNamespace

import pytest

from services import chat_settings, haiku, kids_suggestions


class _FakeClient:
    def __init__(self, content, stop_reason="end_turn"):
        self.calls = []
        self.content = content
        self.stop_reason = stop_reason
        self.messages = SimpleNamespace(create=self._create)

    async def _create(self, **kwargs):
        self.calls.append(kwargs)
        return SimpleNamespace(content=self.content, stop_reason=self.stop_reason)


def _use(monkeypatch, client):
    monkeypatch.setattr(kids_suggestions, "_client", lambda: client)
    monkeypatch.setattr(kids_suggestions.observability, "record_llm_call", lambda *a, **k: None)


def _sent_like_every_other_haiku_call(call):
    assert call["model"] == haiku.MODEL
    assert call["thinking"] == haiku.CALL_KWARGS["thinking"]
    assert "temperature" not in call and "temperature" not in call["extra_body"]


@pytest.mark.anyio
async def test_assignment_suggestion_request(monkeypatch):
    tool = SimpleNamespace(type="tool_use", input={"clear_enough": True, "suggestion": "- Start"})
    client = _FakeClient([tool])
    _use(monkeypatch, client)
    assert await kids_suggestions.assignment_suggestion("Fractions worksheet", "Math") == ("- Start", False)
    _sent_like_every_other_haiku_call(client.calls[0])


@pytest.mark.anyio
async def test_late_policy_request(monkeypatch):
    tool = SimpleNamespace(type="tool_use", input={"understood": True, "shape": "not_accepted"})
    client = _FakeClient([tool])
    _use(monkeypatch, client)
    assert (await kids_suggestions.parse_late_policy("No late work."))["shape"] == "not_accepted"
    _sent_like_every_other_haiku_call(client.calls[0])


@pytest.mark.anyio
async def test_plan_request(monkeypatch):
    client = _FakeClient([SimpleNamespace(type="text", text="1. Math")])
    _use(monkeypatch, client)
    items = [{"title": "Worksheet", "course_name": "Math", "due_date": "2026-11-03", "category": "due"}]
    assert await kids_suggestions.plan(items, "2026-11-02") == "1. Math"
    _sent_like_every_other_haiku_call(client.calls[0])


@pytest.mark.anyio
async def test_refused_plan_is_an_error_not_a_blank_plan(monkeypatch):
    _use(monkeypatch, _FakeClient([], stop_reason="refusal"))
    items = [{"title": "Worksheet", "course_name": "Math", "due_date": "2026-11-03", "category": "due"}]
    with pytest.raises(RuntimeError, match="refusal"):
        await kids_suggestions.plan(items, "2026-11-02")


def test_chat_defaults_are_the_current_models_and_priced():
    settings = chat_settings.ChatbotSettings()
    for audience in (settings.anonymous, settings.signed_in):
        assert audience.model == "claude-haiku-5-5"
        assert audience.escalation_model == "claude-sonnet-5-5"
        assert audience.model in settings.prices and audience.escalation_model in settings.prices
