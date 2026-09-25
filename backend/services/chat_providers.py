"""Model providers for the chatbot, so the agent loop in services/chatbot.py
can run on Anthropic or Gemini (switched in /admin -> Chatbot) without
knowing which.

The conversation history stays in Anthropic's message shape - it's what the
chat widget already replays each turn, so switching providers mid-
conversation keeps working. The Gemini adapter translates to and from
Gemini's OpenAI-compatible API (which also fits Groq etc. later: same wire
format, different base URL and key) on every call.

Provider-only data rides along on history blocks under "_"-prefixed keys
(e.g. a Gemini tool call's extra fields) and is stripped before anything is
sent to Anthropic, whose API rejects unknown keys.
"""

from __future__ import annotations

import json
import logging
import os
import re
import uuid
from dataclasses import dataclass, field
from typing import Any

import httpx
from anthropic import AsyncAnthropic

logger = logging.getLogger(__name__)

GEMINI_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
ANTHROPIC_MODELS_URL = "https://api.anthropic.com/v1/models"

# Gemini's /models lists ~60 ids, most of which can't hold a tool-using chat
# (image/video/music generation, TTS, live audio, embeddings, research
# agents). The admin picks from this list, so a chat model is all it offers.
_GEMINI_NON_CHAT_RE = re.compile(
    r"image|tts|audio|live|embedding|transcribe|translate|robotics|computer-use|customtools"
)


def gemini_chat_model(model_id: str) -> bool:
    return model_id.startswith("gemini-") and not _GEMINI_NON_CHAT_RE.search(model_id)


@dataclass
class Usage:
    input_tokens: int = 0
    output_tokens: int = 0
    cache_read_tokens: int = 0
    cache_write_tokens: int = 0

    def add(self, other: "Usage") -> None:
        self.input_tokens += other.input_tokens
        self.output_tokens += other.output_tokens
        self.cache_read_tokens += other.cache_read_tokens
        self.cache_write_tokens += other.cache_write_tokens


@dataclass
class Completion:
    # Anthropic-shaped assistant content: {"type": "text"} / {"type": "tool_use"} blocks.
    content: list[dict[str, Any]]
    usage: Usage = field(default_factory=Usage)


def _strip_private(blocks: Any) -> Any:
    if not isinstance(blocks, list):
        return blocks
    return [{k: v for k, v in b.items() if not k.startswith("_")} if isinstance(b, dict) else b for b in blocks]


class AnthropicProvider:
    name = "anthropic"

    def __init__(self, api_key: str):
        self.api_key = api_key
        self._client = AsyncAnthropic(api_key=api_key)

    async def complete(self, model: str, system: str, dynamic_system: str | None, tools: list[dict], messages: list[dict], **_: Any) -> Completion:
        # Prompt caching: tools render first, then system, so one breakpoint
        # on the stable system block caches every tool definition too. It's
        # shared by every visitor, so it stays warm across people. Anything
        # that changes (today's date) goes in a block after the breakpoint.
        system_blocks: list[dict[str, Any]] = [{"type": "text", "text": system, "cache_control": {"type": "ephemeral"}}]
        if dynamic_system:
            system_blocks.append({"type": "text", "text": dynamic_system})
        response = await self._client.messages.create(
            model=model,
            max_tokens=1024,
            system=system_blocks,
            tools=tools,
            messages=_with_tail_breakpoint([{**m, "content": _strip_private(m["content"])} for m in messages]),
        )
        # Only text/tool_use blocks are replayed - anthropic==0.34.2 (pinned,
        # shared with content_extractor.py) predates "thinking" content
        # blocks, which the newest models can return unprompted. Its
        # permissive parsing keeps them, but model_dump()'ing one back into
        # a request 400s ("thinking.text: Extra inputs are not permitted").
        content = [block.model_dump() for block in response.content if block.type in ("text", "tool_use")]
        u = response.usage
        return Completion(
            content=content,
            usage=Usage(
                input_tokens=u.input_tokens or 0,
                output_tokens=u.output_tokens or 0,
                cache_read_tokens=getattr(u, "cache_read_input_tokens", None) or 0,
                cache_write_tokens=getattr(u, "cache_creation_input_tokens", None) or 0,
            ),
        )

    async def list_models(self) -> list[str]:
        # The pinned SDK predates the Models API, so this one call is raw HTTP.
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(
                ANTHROPIC_MODELS_URL, params={"limit": 100},
                headers={"x-api-key": self.api_key, "anthropic-version": "2023-06-01"},
            )
            response.raise_for_status()
            return [m["id"] for m in response.json().get("data", [])]


def _with_tail_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A breakpoint on the last block, so a turn's later tool rounds re-read
    the conversation (including big tool results) from cache. Applied to a
    copy: the history goes back to the client and is replayed, and markers
    accumulating there would pass the API's 4-breakpoint limit."""
    if not messages:
        return messages
    last = dict(messages[-1])
    content = last["content"]
    blocks = [{"type": "text", "text": content}] if isinstance(content, str) else [dict(b) for b in content]
    if not blocks:
        return messages
    blocks[-1]["cache_control"] = {"type": "ephemeral"}
    last["content"] = blocks
    return [*messages[:-1], last]


# JSON Schema keywords Gemini's function declarations don't accept.
_GEMINI_DROP_KEYS = {"title", "default", "$schema", "additionalProperties", "examples"}


def _gemini_schema(schema: Any) -> Any:
    """FastMCP's schemas use {"anyOf": [X, {"type": "null"}]} for optional
    params and carry title/default keys; Gemini accepts a subset of JSON
    Schema, so optional-ness becomes just "not in required"."""
    if isinstance(schema, list):
        return [_gemini_schema(s) for s in schema]
    if not isinstance(schema, dict):
        return schema
    any_of = schema.get("anyOf")
    if isinstance(any_of, list):
        non_null = [s for s in any_of if not (isinstance(s, dict) and s.get("type") == "null")]
        if len(non_null) == 1:
            merged = {**{k: v for k, v in schema.items() if k != "anyOf"}, **non_null[0]}
            return _gemini_schema(merged)
    return {k: _gemini_schema(v) for k, v in schema.items() if k not in _GEMINI_DROP_KEYS}


def to_openai_messages(system: str, messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = [{"role": "system", "content": system}]
    for m in messages:
        content = m["content"]
        if isinstance(content, str):
            out.append({"role": m["role"], "content": content})
            continue
        if m["role"] == "user":
            texts = []
            for b in content:
                if b.get("type") == "tool_result":
                    result = b.get("content")
                    if isinstance(result, list):
                        result = "\n".join(x.get("text", "") for x in result if isinstance(x, dict))
                    out.append({"role": "tool", "tool_call_id": b["tool_use_id"], "content": str(result)})
                elif b.get("type") == "text":
                    texts.append(b["text"])
            if texts:
                out.append({"role": "user", "content": "\n".join(texts)})
            continue
        # assistant
        msg: dict[str, Any] = {"role": "assistant", "content": "".join(b.get("text", "") for b in content if b.get("type") == "text") or None}
        calls = [
            {
                "id": b["id"],
                "type": "function",
                "function": {"name": b["name"], "arguments": json.dumps(b.get("input") or {})},
                # Echo back whatever else the provider attached to the call
                # (e.g. a Gemini thought signature) exactly as received.
                **(b.get("_openai_extra") or {}),
            }
            for b in content
            if b.get("type") == "tool_use"
        ]
        if calls:
            msg["tool_calls"] = calls
        out.append(msg)
    return out


def from_openai_message(message: dict[str, Any]) -> list[dict[str, Any]]:
    blocks: list[dict[str, Any]] = []
    if message.get("content"):
        blocks.append({"type": "text", "text": message["content"]})
    for call in message.get("tool_calls") or []:
        fn = call.get("function") or {}
        try:
            args = json.loads(fn.get("arguments") or "{}")
        except ValueError:
            args = {}
        extra = {k: v for k, v in call.items() if k not in ("id", "type", "function", "index")}
        block: dict[str, Any] = {
            "type": "tool_use",
            # Anthropic ids must match ^[a-zA-Z0-9_-]+$ - keep history portable
            # if the admin switches providers mid-conversation.
            "id": "".join(ch for ch in (call.get("id") or "") if ch.isalnum() or ch in "_-") or f"call_{uuid.uuid4().hex[:16]}",
            "name": fn.get("name", ""),
            "input": args if isinstance(args, dict) else {},
        }
        if extra:
            block["_openai_extra"] = extra
        blocks.append(block)
    return blocks


class OpenAICompatibleProvider:
    """Gemini via its OpenAI-compatible endpoint (and, later, anything else
    that speaks the same wire format). Raw httpx - no new dependency."""

    def __init__(self, name: str, base_url: str, api_key: str, *, schema_fixer=None, model_filter=None):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.api_key = api_key
        self._schema_fixer = schema_fixer or (lambda s: s)
        self._model_filter = model_filter or (lambda _m: True)

    async def complete(
        self, model: str, system: str, dynamic_system: str | None, tools: list[dict], messages: list[dict],
        reasoning_effort: str | None = None, **_: Any,
    ) -> Completion:
        full_system = f"{system}\n\n{dynamic_system}" if dynamic_system else system
        body: dict[str, Any] = {
            "model": model,
            # Gemini's thinking tokens count against this, so it's larger than
            # the 1024 used for Claude - too small and a reply comes back empty.
            "max_tokens": 4096,
            "messages": to_openai_messages(full_system, messages),
            "tools": [
                {"type": "function", "function": {"name": t["name"], "description": t.get("description") or "", "parameters": self._schema_fixer(t["input_schema"])}}
                for t in tools
            ],
        }
        if reasoning_effort:
            body["reasoning_effort"] = reasoning_effort
        async with httpx.AsyncClient(timeout=90) as client:
            response = await client.post(
                f"{self.base_url}/chat/completions", json=body, headers={"Authorization": f"Bearer {self.api_key}"},
            )
        if response.status_code >= 400:
            raise RuntimeError(f"{self.name} returned {response.status_code}: {response.text[:500]}")
        data = response.json()
        message = (data.get("choices") or [{}])[0].get("message") or {}
        u = data.get("usage") or {}
        cached = ((u.get("prompt_tokens_details") or {}).get("cached_tokens")) or 0
        return Completion(
            content=from_openai_message(message),
            usage=Usage(
                # Reported like Anthropic's: input excludes what was read from cache.
                input_tokens=(u.get("prompt_tokens") or 0) - cached,
                output_tokens=u.get("completion_tokens") or 0,
                cache_read_tokens=cached,
            ),
        )

    async def list_models(self) -> list[str]:
        async with httpx.AsyncClient(timeout=15) as client:
            response = await client.get(f"{self.base_url}/models", headers={"Authorization": f"Bearer {self.api_key}"})
            response.raise_for_status()
            ids = (m["id"].removeprefix("models/") for m in response.json().get("data", []))
            return sorted(i for i in ids if self._model_filter(i))


def configured_providers() -> dict[str, Any]:
    """Providers with a key set. The chatbot's Anthropic key is its own spend
    pool (CHATBOT_ANTHROPIC_API_KEY) with the shared key as a fallback - see
    services/chatbot.py."""
    providers: dict[str, Any] = {}
    anthropic_key = os.getenv("CHATBOT_ANTHROPIC_API_KEY") or os.getenv("ANTHROPIC_API_KEY")
    if anthropic_key:
        providers["anthropic"] = AnthropicProvider(anthropic_key)
    gemini_key = os.getenv("CHATBOT_GEMINI_API_KEY") or os.getenv("GEMINI_API_KEY")
    if gemini_key:
        providers["gemini"] = OpenAICompatibleProvider(
            "gemini", GEMINI_BASE_URL, gemini_key, schema_fixer=_gemini_schema, model_filter=gemini_chat_model
        )
    return providers


KNOWN_PROVIDERS = ("anthropic", "gemini")
