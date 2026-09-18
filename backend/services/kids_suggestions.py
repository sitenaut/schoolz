"""On-demand AI suggestions for the Kids view (docs/KIDS_VIEW_V2_DESIGN.md §7).

Two tiers, deliberately different:

- assignment_suggestion(): sees ONLY an assignment's title and course name.
  routers/bucket3.py caches the result in AssignmentSuggestion, shared by every
  student in that course section - so nothing personal (the student's name,
  grade, due status, or the assignment's description text) may ever be sent:
  another family's child reads the same row.
- plan(): one student's own current list (titles, course names, due dates,
  overdue or not), never cached - the input changes whenever the list does.

Both run only when a person clicks a button - never on import, never on a
schedule.
"""
from __future__ import annotations

import os
import time

from anthropic import AsyncAnthropic

import observability

MODEL = "claude-haiku-4-5-20251001"
MAX_PLAN_ITEMS = 25


class SuggestionsUnavailable(Exception):
    pass


_ASSIGNMENT_SYSTEM = """You help a middle or high school student get started on one assignment. You know ONLY its title and course name. Many students and parents reading this have ADHD: be short, concrete, and calm.

If the title doesn't say what the work actually is (for example "Assignment 3", "Classwork", "Do Now", "Untitled Formative 817", a bare date), set clear_enough=false and leave suggestion empty. Never guess at content you can't see.

Otherwise set clear_enough=true and write at most 3 short bullet points, each starting with "- ": first a step that takes under 5 minutes, then how to break up the rest. No preamble, no pep talk, nothing about grades. Don't invent requirements, page numbers, due dates, or rubric details."""

_ASSIGNMENT_TOOL = {
    "name": "record_suggestion",
    "description": "Record how a student could approach this assignment, or that the title is too vague to say.",
    "input_schema": {
        "type": "object",
        "properties": {
            "clear_enough": {
                "type": "boolean",
                "description": "True only if the title says concretely what the work is.",
            },
            "suggestion": {
                "type": "string",
                "description": "Up to 3 short '- ' bullets. Empty string when clear_enough is false.",
            },
        },
        "required": ["clear_enough", "suggestion"],
    },
}

_PLAN_SYSTEM = """You help a student decide what order to tackle their schoolwork in. You see only assignment titles, course names, due dates, and whether each is overdue. Many readers have ADHD: be brief and decisive.

Write at most 5 numbered steps ("1. "). Overdue work goes first, then whatever is due soonest; group tiny tasks from the same class into one step. Each step is one line: the assignment title in bold (**Title**), then a few words on why it's next or roughly how long it takes. After the steps, one short line suggesting a short break after step 2 or 3. No preamble, no lecture, no mention of grades, no invented details beyond the titles."""


def _client() -> AsyncAnthropic:
    key = os.getenv("ANTHROPIC_API_KEY", "")
    if not key:
        raise SuggestionsUnavailable("ANTHROPIC_API_KEY is not configured")
    return AsyncAnthropic(api_key=key)


async def assignment_suggestion(title: str, course_name: str | None) -> tuple[str | None, bool]:
    """(suggestion_text, declined). Declined means the title was too vague -
    the caller stores that too, so the same vague title isn't re-sent."""
    client = _client()
    started = time.perf_counter()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=400,
        temperature=0,
        system=_ASSIGNMENT_SYSTEM,
        tools=[_ASSIGNMENT_TOOL],
        tool_choice={"type": "tool", "name": "record_suggestion"},
        messages=[{"role": "user", "content": f"Course: {course_name or 'unknown'}\nAssignment title: {title}"}],
    )
    observability.record_llm_call("kids_assignment_suggestion", MODEL, response, time.perf_counter() - started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return None, True
    text = (tool_use.input.get("suggestion") or "").strip()
    if not tool_use.input.get("clear_enough") or not text:
        return None, True
    return text, False


async def plan(items: list[dict], today_iso: str) -> str:
    """`items`: current Missing + Due to-do dicts (title, course_name,
    due_date, category) - already the minimal fields; nothing else is sent."""
    client = _client()
    lines = []
    for i in items[:MAX_PLAN_ITEMS]:
        when = f"OVERDUE (was due {i['due_date']})" if i["category"] == "missing" else f"due {i['due_date']}"
        lines.append(f"- {i['title']} [{i.get('course_name') or 'unknown course'}] {when}")
    started = time.perf_counter()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=500,
        temperature=0.2,
        system=_PLAN_SYSTEM,
        messages=[{"role": "user", "content": f"Today is {today_iso}.\n\n" + "\n".join(lines)}],
    )
    observability.record_llm_call("kids_plan", MODEL, response, time.perf_counter() - started)
    return "".join(b.text for b in response.content if b.type == "text").strip()
