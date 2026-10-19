"""Every Claude call is metered (observability.record_llm_call).

An unmetered call is invisible to the Cost dashboard and to the token-use and
truncation alerts, and nothing else fails when one is added. A file that
calls `messages.create` must call `record_llm_call` at least as often.
"""
from pathlib import Path
from types import SimpleNamespace

import observability
from services import chatbot
from services.chat_providers import Completion, Usage

BACKEND = Path(__file__).resolve().parents[1]

# Files whose calls are metered somewhere else, and where.
METERED_ELSEWHERE = {
    # Every provider's completion is recorded by chatbot._record_usage.
    "services/chat_providers.py",
}


def test_every_messages_create_is_metered():
    unmetered = []
    for path in sorted(BACKEND.rglob("*.py")):
        rel = path.relative_to(BACKEND).as_posix()
        if rel.startswith("tests/") or rel in METERED_ELSEWHERE:
            continue
        text = path.read_text(encoding="utf-8")
        calls = text.count("messages.create(")
        if calls and text.count("record_llm_call(") < calls:
            unmetered.append(f"{rel}: {calls} messages.create, {text.count('record_llm_call(')} record_llm_call")
    assert not unmetered, "Claude calls without observability.record_llm_call:\n" + "\n".join(unmetered)


def test_chat_usage_reaches_the_llm_counters(monkeypatch):
    seen = []
    monkeypatch.setattr(observability, "record_llm_call", lambda *args: seen.append(args))
    completion = Completion(content=[], usage=Usage(10, 20, 30, 40), stop_reason="max_tokens")

    chatbot._record_usage("claude-haiku-4-5", completion, 1.5)

    purpose, model, response, duration = seen[0]
    assert (purpose, model, duration) == ("chat", "claude-haiku-4-5", 1.5)
    assert response.stop_reason == "max_tokens"
    assert vars(response.usage) == vars(SimpleNamespace(
        input_tokens=10, output_tokens=20, cache_read_input_tokens=30, cache_creation_input_tokens=40,
    ))
