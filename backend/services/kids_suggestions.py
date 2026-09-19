"""On-demand AI calls for the Kids view (docs/KIDS_VIEW_V2_DESIGN.md §7).

Three, deliberately different:

- assignment_suggestion(): sees ONLY an assignment's title and course name.
  routers/bucket3.py caches the result in AssignmentSuggestion, shared by every
  student in that course section - so nothing personal (the student's name,
  grade, due status, or the assignment's description text) may ever be sent:
  another family's child reads the same row.
- plan(): one student's own current list (titles, course names, due dates,
  overdue or not), never cached - the input changes whenever the list does.
- parse_late_policy(): a syllabus paragraph the parent pasted in, turned into a
  structured CourseLatePolicy proposal. Sees only that paragraph. The result is
  never saved directly - it comes back as a proposal the parent confirms, since
  a misread late policy silently changes what the dashboard tells a kid to work
  on next.

All run only when a person clicks a button - never on import, never on a
schedule.
"""
from __future__ import annotations

import os
import time

from anthropic import AsyncAnthropic

import observability

MODEL = "claude-haiku-4-5-20251001"
MAX_PLAN_ITEMS = 25
# A syllabus late-work paragraph is a few sentences; this is a generous cap
# that still stops someone pasting an entire handbook into a model call.
MAX_POLICY_CHARS = 4000


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


_LATE_POLICY_SYSTEM = """You read one paragraph from a class syllabus and record its LATE WORK policy as structured data. You are transcribing, not advising.

Pick the shape that matches what the text actually says:
- full_credit: late work accepted with no deduction
- flat: one fixed deduction regardless of how late (penalty_pct)
- daily_decay: a deduction per day late (penalty_per_day), optionally never below floor_pct
- window: full credit if handed in within window_days, nothing accepted after
- tiered: explicit bands, e.g. "1 day late 90%, 2 days 80%, after that zero" -> steps
- not_accepted: late work is not accepted at all

Rules you must follow:
- Record ONLY what the text states. If it doesn't give a number, leave that field out - never infer a typical value.
- If the paragraph is not about late work at all, or is too vague to place in one shape, set understood=false and leave everything else empty.
- accepted_until: "marking_period_end" if it says end of marking period/quarter/term, an ISO date if it gives one, otherwise leave out.
- applies_to_types: only if the text limits the rule (e.g. homework but not tests). Use values from: assignment, quiz, material, announcement, question.
- extension_by_request: true only if it says an extension/exception is available by asking beforehand.
- source_sentence: copy the exact sentence(s) the policy came from, verbatim."""

_LATE_POLICY_TOOL = {
    "name": "record_late_policy",
    "description": "Record a class's late-work policy exactly as the syllabus states it.",
    "input_schema": {
        "type": "object",
        "properties": {
            "understood": {
                "type": "boolean",
                "description": "True only if the text clearly states a late-work policy.",
            },
            "shape": {
                "type": "string",
                "enum": ["full_credit", "flat", "daily_decay", "window", "tiered", "not_accepted"],
            },
            "penalty_pct": {"type": "number", "description": "Percentage points deducted, for shape=flat."},
            "penalty_per_day": {"type": "number", "description": "Points deducted per day, for shape=daily_decay."},
            "floor_pct": {"type": "number", "description": "Lowest percentage the decay can reach."},
            "window_days": {"type": "integer", "description": "Days late still accepted, for shape=window."},
            "steps": {
                "type": "array",
                "description": "For shape=tiered: within `days` days late, `credit_pct` is earnable.",
                "items": {
                    "type": "object",
                    "properties": {"days": {"type": "integer"}, "credit_pct": {"type": "number"}},
                    "required": ["days", "credit_pct"],
                },
            },
            "accepted_until": {"type": "string", "description": '"marking_period_end" or an ISO date.'},
            "applies_to_types": {"type": "array", "items": {"type": "string"}},
            "extension_by_request": {"type": "boolean"},
            "source_sentence": {"type": "string", "description": "The exact sentence(s) this came from."},
            "summary": {
                "type": "string",
                "description": "One plain sentence restating the rule, for the parent to check against the handout.",
            },
        },
        "required": ["understood"],
    },
}


async def parse_late_policy(text: str) -> dict:
    """A pasted syllabus paragraph -> a proposed policy dict (never saved
    here). `understood: False` means it couldn't be placed in one of the
    shapes - the caller shows the manual form rather than a guess."""
    client = _client()
    started = time.perf_counter()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=700,
        temperature=0,
        system=_LATE_POLICY_SYSTEM,
        tools=[_LATE_POLICY_TOOL],
        tool_choice={"type": "tool", "name": "record_late_policy"},
        messages=[{"role": "user", "content": text[:MAX_POLICY_CHARS]}],
    )
    observability.record_llm_call("kids_late_policy_parse", MODEL, response, time.perf_counter() - started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use or not tool_use.input.get("understood"):
        return {"understood": False}
    return dict(tool_use.input)


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
