"""The chatbot's personal tools - offered only when the /chat request itself
carries a valid login, and never registered on the public MCP server at
/mcp (that server holds no credentials and stays public-data-only by
design; see mcp_server.py).

Every tool calls this app's own authenticated route in-process with the
caller's *own* bearer token forwarded, the same way the frontend would.
That's the whole security model, on purpose: no new access code exists
here. Whether this user may see a given student is decided by exactly the
check the Kids view already uses (`_get_own_student` - guardian or the
student themselves), so the chatbot can never see more than the person
could by clicking around the site. A student_id the model invents or picks
up from a spoofed history just comes back as that route's 404.

Only GETs - the assistant can read the personal layer, never change it.
"""

import json
import logging
import re
from typing import Any

import httpx
from fastapi import FastAPI

logger = logging.getLogger(__name__)

# Route ids are UUIDs; anything else is rejected before it gets anywhere
# near a URL path (no "../", no query smuggling from a model-built string).
_ID_RE = re.compile(r"^[A-Za-z0-9-]{1,64}$")

# A tool result is re-sent to the model on every later round of the turn,
# and the client replays it on every later turn - a full year of work
# items would cost real money per message for no better answer.
_MAX_RESULT_CHARS = 20_000

_STUDENT_ARG = {
    "type": "object",
    "properties": {
        "student_id": {"type": "string", "description": "The student's id, from list_my_children."},
    },
    "required": ["student_id"],
}

# name -> (description, input_schema, path template)
_TOOLS: dict[str, tuple[str, dict[str, Any], str]] = {
    "list_my_children": (
        "The signed-in person's own students: every child they're a guardian of, plus their own record if they "
        "are a student. Each has an id (pass it to the other personal tools), name, school, and grad_year. "
        "Call this first for any question about 'my kid', a child by name, grades, homework, or schedule.",
        {"type": "object", "properties": {}},
        "",  # special-cased: merges two routes
    ),
    "get_child_todo": (
        "A student's current-marking-period work: missing, due (upcoming), done, and no-due-date items, each with "
        "course, title, due date and late-credit info, plus overall progress and the single suggested next action.",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/todo",
    ),
    "get_child_grades": (
        "Per-course progress for a student's current marking period: the course grade, graded entries, and "
        "missing/due counts per class.",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/progress",
    ),
    "get_child_schedule": (
        "A student's class schedule: today's periods (with the rotation-day label), the full period list, and "
        "upcoming school days.",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/schedule",
    ),
    "get_child_right_now": (
        "Which class a student is in right now and which is next, with room, teacher and teacher email.",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/right-now",
    ),
    "get_child_announcements": (
        "The most recent Google Classroom announcements from a student's teachers, newest first.",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/announcements",
    ),
    "get_child_teacher_emails": (
        "Every teacher seen for a student, mapped to their email from the school's staff directory "
        "(an empty list means no confident match - never guess one).",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/teacher-emails",
    ),
    "get_child_late_policies": (
        "The late-work policies on file for a student's classes (typed in by the family from the syllabus).",
        _STUDENT_ARG,
        "/students/{student_id}/bucket3/late-policies",
    ),
    "get_child_specials": (
        "An elementary student's specials (Art, PE, Music, ...) by rotation day.",
        _STUDENT_ARG,
        "/students/{student_id}/specials",
    ),
    "list_my_notifications": (
        "The signed-in person's schoolz notifications (e.g. another guardian linked to their child), newest first.",
        {"type": "object", "properties": {}},
        "/notifications",
    ),
    "list_my_schools": (
        "The schools the signed-in person's children attend.",
        {"type": "object", "properties": {}},
        "/schools/mine",
    ),
}

PERSONAL_TOOL_NAMES = frozenset(_TOOLS)

PERSONAL_PROMPT = (
    " The person you're talking with is signed in, so you also have personal tools for their own children "
    "(or, for a student, themselves): to-dos, grades, schedule, announcements, teacher emails, late policies, "
    "specials, and notifications. Start with list_my_children to get student ids; if they have more than one "
    "child and the question doesn't say which, ask. This data came from their own school accounts - answer "
    "about it plainly, and never mention one child's data when asked about another."
)


def anthropic_tool_defs() -> list[dict[str, Any]]:
    return [{"name": name, "description": desc, "input_schema": schema} for name, (desc, schema, _) in _TOOLS.items()]


class PersonalTools:
    """One signed-in caller's tool executor, built per /chat request."""

    def __init__(self, app: FastAPI, token: str):
        self._client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://schoolz-internal",
            headers={"Authorization": f"Bearer {token}"},
            timeout=30.0,
        )

    async def aclose(self) -> None:
        await self._client.aclose()

    async def _get(self, path: str) -> Any:
        response = await self._client.get(path)
        if response.status_code >= 400:
            return {"error": f"{response.status_code} {response.reason_phrase}", "detail": response.text[:500]}
        return response.json()

    async def run(self, name: str, arguments: dict[str, Any]) -> str:
        _desc, _schema, template = _TOOLS[name]
        student_id = str(arguments.get("student_id", ""))
        if "{student_id}" in template and not _ID_RE.match(student_id):
            return json.dumps({"error": "student_id must be an id from list_my_children"})
        try:
            if name == "list_my_children":
                data = await self._list_my_children()
            else:
                data = await self._get(template.format(student_id=student_id))
        except Exception as exc:  # noqa: BLE001 - same as chatbot._run_tool: one bad call shouldn't 500 the turn
            logger.exception("chatbot_personal_tool_failed", extra={"tool": name})
            return json.dumps({"error": f"{type(exc).__name__}: {exc}"})
        text = json.dumps(data, default=str)
        if len(text) > _MAX_RESULT_CHARS:
            text = text[:_MAX_RESULT_CHARS] + '..."[truncated - ask about one class or a narrower question]"'
        return text

    async def _list_my_children(self) -> Any:
        children = await self._get("/students")
        if isinstance(children, dict):  # an error
            return children
        me = await self._get("/auth/me")
        own_id = me.get("student_profile_id") if isinstance(me, dict) else None
        if own_id and all(c.get("id") != own_id for c in children):
            children.append({"id": own_id, "note": "This is the signed-in student's own record."})
        return {"count": len(children), "items": children}
