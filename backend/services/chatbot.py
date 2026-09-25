"""The on-site chat assistant: an agentic loop over the exact same public,
no-auth tools registered on the MCP server at /mcp (see mcp_server.py) -
this endpoint is effectively just another MCP client, sharing that
server's tool definitions and execution rather than duplicating them.

Runs on Haiku by default and escalates to Sonnet for compound or
multi-tool questions - see _should_escalate. Uses ITS OWN Anthropic API
key/spend pool (CHATBOT_ANTHROPIC_API_KEY), separate from the one
services/content_extractor.py uses for newsletter extraction: that job is
internal and scheduled, this endpoint is public and unauthenticated, so a
traffic spike (or abuse) on one shouldn't be able to exhaust the other's
budget. Falls back to the shared ANTHROPIC_API_KEY if no dedicated key is
set, but logs a warning every time that fallback is used so it doesn't go
unnoticed in prod.
"""

import json
import logging
import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo
from typing import Any

from anthropic import AsyncAnthropic
from mcp.server.fastmcp import FastMCP

from services.chatbot_personal import PERSONAL_PROMPT, PERSONAL_TOOL_NAMES, PersonalTools

logger = logging.getLogger(__name__)

_DEDICATED_KEY = os.getenv("CHATBOT_ANTHROPIC_API_KEY", "")
_SHARED_KEY = os.getenv("ANTHROPIC_API_KEY", "")
ANTHROPIC_API_KEY = _DEDICATED_KEY or _SHARED_KEY

HAIKU = "claude-haiku-4-5-20251001"
SONNET = "claude-sonnet-5"

# A hard ceiling on tool-call round trips within one turn - this is a
# public, unauthenticated endpoint, so a model that gets stuck chasing its
# own tail (or a caller trying to provoke that) has a real dollar cost per
# extra round, not just a slow response.
MAX_TOOL_ROUNDS = 4

SYSTEM_PROMPT = (
    "You are schoolz's assistant for Cherry Hill Public Schools. Answer using only the "
    "tools available to you - school info, today's status, bell schedules, lunch menus, "
    "transportation, calendar items, tracked newsletters, and high-school class-year "
    "pages (their content and payment schedules). Never invent a fact a tool didn't "
    "return. If a lookup comes back with a 'note' about missing data, relay that note's "
    "suggestion (ask the school to publish it, or submit a link with "
    "submit_community_content) instead of just saying there's no data. Keep answers "
    "short and concrete - most people are reading this on a phone. Plain text only - "
    "no markdown (no **bold**, no bullet/numbered lists, no headers) - this is rendered "
    "as plain text, so markdown syntax would show up as literal asterisks and dashes."
)


def _should_escalate(message: str, tool_rounds_so_far: int, already_escalated: bool) -> bool:
    """A cheap heuristic, deliberately not a model call - classifying the
    question with an LLM would cost about as much as just answering it on
    Haiku, which defeats the entire point of a cheap default model.
    """
    if already_escalated:
        return True
    if tool_rounds_so_far >= 2:
        return True
    signals = [
        len(re.findall(r"\b(and|or|compare|versus|vs\.?)\b", message, re.I)) >= 2,
        len(message) > 240,
        bool(re.search(r"\b(all (of )?my|both|every)\b.*\bschools?\b", message, re.I)),
    ]
    return sum(signals) >= 1


async def _anthropic_tools(mcp: FastMCP) -> list[dict[str, Any]]:
    tools = await mcp.list_tools()
    return [{"name": t.name, "description": t.description, "input_schema": t.inputSchema} for t in tools]


async def _run_tool(mcp: FastMCP, name: str, arguments: dict[str, Any]) -> str:
    try:
        content = await mcp.call_tool(name, arguments)
    except Exception as exc:  # noqa: BLE001 - a bad/unknown tool call shouldn't 500 the whole turn
        logger.exception("chatbot_tool_call_failed", extra={"tool": name})
        return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
    parts = [block.text for block in content if hasattr(block, "text")]
    return "\n".join(parts) if parts else "null"


def _with_tail_breakpoint(messages: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """A copy of `messages` with a cache breakpoint on the last block, so a
    turn's later tool rounds re-read the conversation (including big tool
    results) from cache. A copy, never the list itself: the history goes
    back to the client and is replayed next turn, and markers accumulating
    there would pass the API's limit of 4 breakpoints per request.
    """
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


def _log_usage(model: str, usage: Any) -> None:
    # Read back in Loki as structured metadata: cache_read vs input shows
    # whether caching is actually hitting (a silent invalidator shows up as
    # cache_read_tokens stuck at 0).
    logger.info(
        "chatbot_usage",
        extra={
            "model": model,
            "input_tokens": getattr(usage, "input_tokens", None),
            "output_tokens": getattr(usage, "output_tokens", None),
            "cache_read_tokens": getattr(usage, "cache_read_input_tokens", None),
            "cache_write_tokens": getattr(usage, "cache_creation_input_tokens", None),
        },
    )


async def run_chat_turn(
    mcp: FastMCP,
    history: list[dict[str, Any]],
    message: str,
    already_escalated: bool,
    personal: PersonalTools | None = None,
) -> dict[str, Any]:
    """One user turn. `history` is exactly the plain role/content list the
    client sent back from the previous turn's response - this endpoint
    keeps no server-side conversation storage (it's public/anonymous, and
    there's no reason to hold onto a transcript of what someone asked).
    `already_escalated` is likewise echoed back by the client so escalation
    stays sticky for the rest of a conversation without needing a session
    store.

    `personal` is set only for a signed-in caller (routers/chat.py) and adds
    the tools in services/chatbot_personal.py on top of the public ones.
    """
    if not ANTHROPIC_API_KEY:
        return {
            "reply": "The assistant isn't configured yet - ask a schoolz admin to set an Anthropic API key.",
            "model": None,
            "history": history,
            "escalated": already_escalated,
        }
    if not _DEDICATED_KEY:
        logger.warning(
            "chatbot_using_shared_anthropic_key",
            extra={"note": "set CHATBOT_ANTHROPIC_API_KEY for a spend limit independent of newsletter extraction"},
        )

    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    tools = await _anthropic_tools(mcp)
    stable_system = SYSTEM_PROMPT
    if personal:
        tools += await personal.tool_defs()
        stable_system += PERSONAL_PROMPT
    # Prompt caching: tools render first, then system, so one breakpoint on
    # the stable system block caches every tool definition too (~4.3k tokens
    # anonymous, ~5.6k signed in - over Haiku 4.5's 4,096-token minimum, but
    # only just for anonymous; a much shorter prompt would silently stop
    # caching). The prefix is shared by every visitor, so it stays warm
    # across people, not just within one conversation. Anything that changes
    # - like today's date - goes in a block *after* the breakpoint.
    system: list[dict[str, Any]] = [{"type": "text", "text": stable_system, "cache_control": {"type": "ephemeral"}}]
    if personal:
        system.append({"type": "text", "text": f"Today is {datetime.now(ZoneInfo('America/New_York')):%A, %B %-d, %Y}."})

    escalated = already_escalated
    model = SONNET if escalated else HAIKU

    messages: list[dict[str, Any]] = list(history)
    messages.append({"role": "user", "content": message})

    tool_rounds = 0
    final_text = ""
    used_model = model

    while True:
        response = await client.messages.create(
            model=model,
            max_tokens=1024,
            system=system,
            tools=tools,
            messages=_with_tail_breakpoint(messages),
        )
        used_model = model
        _log_usage(model, response.usage)
        # Only text/tool_use blocks are replayed - anthropic==0.34.2 (pinned,
        # shared with content_extractor.py) predates "thinking" content
        # blocks, which the newest models can return unprompted even
        # without extended thinking requested. Its permissive parsing keeps
        # them around, but model_dump()'ing one back into a request 400s
        # ("thinking.text: Extra inputs are not permitted") - the SDK's
        # loose parse isn't the API's strict input shape. Not needed here
        # anyway: interleaved-thinking continuity is a deliberate opt-in
        # feature (beta header) this endpoint doesn't use.
        messages.append(
            {
                "role": "assistant",
                "content": [block.model_dump() for block in response.content if block.type in ("text", "tool_use")],
            }
        )

        tool_uses = [b for b in response.content if b.type == "tool_use"]
        if not tool_uses:
            final_text = "".join(b.text for b in response.content if b.type == "text")
            break

        tool_rounds += 1
        if not escalated and _should_escalate(message, tool_rounds, escalated):
            # Escalate mid-turn, not just on the next call - a Haiku
            # response already spinning through 2+ tool calls is exactly
            # the case worth upgrading before it produces a shaky answer.
            escalated = True
            model = SONNET

        if tool_rounds > MAX_TOOL_ROUNDS:
            final_text = "That's a more involved question than I can chase down right now - try narrowing it to one school or one topic."
            break

        results = []
        for use in tool_uses:
            if use.name in PERSONAL_TOOL_NAMES:
                result_text = (
                    await personal.run(use.name, use.input)
                    if personal
                    else json.dumps({"error": "Sign in to schoolz to ask about your own children."})
                )
            else:
                result_text = await _run_tool(mcp, use.name, use.input)
            results.append({"type": "tool_result", "tool_use_id": use.id, "content": result_text})
        messages.append({"role": "user", "content": results})

    return {"reply": final_text, "model": used_model, "history": messages, "escalated": escalated}
