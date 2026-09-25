"""The on-site chat assistant: an agentic loop over the exact same public,
no-auth tools registered on the MCP server at /mcp (see mcp_server.py) -
this endpoint is effectively just another MCP client, sharing that
server's tool definitions and execution rather than duplicating them.

Runs on Haiku by default and escalates to Sonnet for compound or
multi-tool questions - see _should_escalate. The provider and both models
are switchable per audience in /admin -> Chatbot (services/chat_settings.py,
services/chat_providers.py), e.g. to compare Gemini against Claude. Uses ITS OWN Anthropic API
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

from mcp.server.fastmcp import FastMCP

from services.chat_providers import Usage, configured_providers
from services.chat_settings import AudienceConfig
from services.chatbot_personal import PERSONAL_PROMPT, PERSONAL_TOOL_NAMES, PersonalTools

logger = logging.getLogger(__name__)

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
    "short and concrete - most people are reading this on a phone. Formatting: the chat "
    "renders a small markdown subset - **bold**, '- ' bullet lists, '1. ' numbered lists, "
    "[text](url) links, and a blank line between groups. Nothing else (no headers, tables, "
    "or code blocks). Use it only when it helps scanning: a one-fact answer stays one "
    "plain sentence. For a list of events or dated items, group by day - the day as its "
    "own bold line (**Saturday, Oct 3**), then one '- ' bullet per item: time first, then "
    "the title (as a [title](url) link when there's a url), then the place, e.g. "
    "'- 10:00 AM · [Fall Festival](https://...) · Croft Farm'. Keep each bullet to one line; "
    "put a price or 'free' at the end only if known."
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


def _log_usage(provider: str, model: str, usage: Usage) -> None:
    # Read back in Loki as structured metadata: cache_read vs input shows
    # whether caching is actually hitting (a silent invalidator shows up as
    # cache_read_tokens stuck at 0).
    logger.info(
        "chatbot_usage",
        extra={
            "provider": provider,
            "model": model,
            "input_tokens": usage.input_tokens,
            "output_tokens": usage.output_tokens,
            "cache_read_tokens": usage.cache_read_tokens,
            "cache_write_tokens": usage.cache_write_tokens,
        },
    )


async def run_chat_turn(
    mcp: FastMCP,
    history: list[dict[str, Any]],
    message: str,
    already_escalated: bool,
    personal: PersonalTools | None = None,
    config: AudienceConfig | None = None,
    providers: dict[str, Any] | None = None,
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
    `config` picks the provider and models (admin-editable, see
    services/chat_settings.py); the default is Haiku escalating to Sonnet.
    """
    config = config or AudienceConfig()
    providers = providers if providers is not None else configured_providers()
    provider = providers.get(config.provider)
    if provider is None:
        return {
            "reply": f"The assistant isn't configured yet - ask a schoolz admin to set an API key for {config.provider}.",
            "model": None,
            "history": history,
            "escalated": already_escalated,
        }
    if config.provider == "anthropic" and not os.getenv("CHATBOT_ANTHROPIC_API_KEY"):
        logger.warning(
            "chatbot_using_shared_anthropic_key",
            extra={"note": "set CHATBOT_ANTHROPIC_API_KEY for a spend limit independent of newsletter extraction"},
        )

    tools = await _anthropic_tools(mcp)
    stable_system = SYSTEM_PROMPT
    if personal:
        tools += await personal.tool_defs()
        stable_system += PERSONAL_PROMPT
    # Kept out of the stable system text so the cached prefix doesn't change
    # daily (see AnthropicProvider.complete).
    dynamic_system = f"Today is {datetime.now(ZoneInfo('America/New_York')):%A, %B %-d, %Y}." if personal else None

    escalated = already_escalated and bool(config.escalation_model)
    model = config.escalation_model if escalated else config.model

    messages: list[dict[str, Any]] = list(history)
    messages.append({"role": "user", "content": message})

    tool_rounds = 0
    final_text = ""
    used_model = model
    usage_by_model: dict[str, Usage] = {}
    tools_called: list[str] = []

    while True:
        completion = await provider.complete(
            model=model, system=stable_system, dynamic_system=dynamic_system, tools=tools, messages=messages,
            reasoning_effort=config.reasoning_effort,
        )
        used_model = model
        usage_by_model.setdefault(model, Usage()).add(completion.usage)
        _log_usage(config.provider, model, completion.usage)
        messages.append({"role": "assistant", "content": completion.content})

        tool_uses = [b for b in completion.content if b.get("type") == "tool_use"]
        if not tool_uses:
            final_text = "".join(b.get("text", "") for b in completion.content if b.get("type") == "text")
            break

        tool_rounds += 1
        if not escalated and config.escalation_model and _should_escalate(message, tool_rounds, escalated):
            # Escalate mid-turn, not just on the next call - a cheap model
            # already spinning through 2+ tool calls is exactly the case
            # worth upgrading before it produces a shaky answer.
            escalated = True
            model = config.escalation_model

        if tool_rounds > MAX_TOOL_ROUNDS:
            final_text = "That's a more involved question than I can chase down right now - try narrowing it to one school or one topic."
            break

        results = []
        for use in tool_uses:
            tools_called.append(use["name"])
            if use["name"] in PERSONAL_TOOL_NAMES:
                result_text = (
                    await personal.run(use["name"], use.get("input") or {})
                    if personal
                    else json.dumps({"error": "Sign in to schoolz to ask about your own children."})
                )
            else:
                result_text = await _run_tool(mcp, use["name"], use.get("input") or {})
            results.append({"type": "tool_result", "tool_use_id": use["id"], "content": result_text})
        messages.append({"role": "user", "content": results})

    return {
        "reply": final_text,
        "model": used_model,
        "history": messages,
        "escalated": escalated,
        # Not part of the public /chat response - read by the admin compare panel.
        "provider": config.provider,
        "usage_by_model": usage_by_model,
        "tools_called": tools_called,
        "rounds": tool_rounds,
    }
