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
from collections import defaultdict
from datetime import date, datetime, time
from typing import Any
from zoneinfo import ZoneInfo

import httpx
from fastapi import FastAPI

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")

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

# Local events (/local) - signed-in only, same as the page. Special-cased in
# run(): the raw list is far too big to hand the model as-is (~335 events a
# week, ~440 of them recurring YMCA classes), so the tool trims it first.
_TOOLS["find_local_events"] = (
    "Community events near Cherry Hill (township calendars, libraries, the Y, concerts, festivals) between two "
    "dates. For 'what can I take the kids to', don't rely on categories alone - the family/kids tags are "
    "keyword-inferred and miss plenty; search the whole range and judge from each title and description. "
    "Categories in use: family, kids, teen, outdoor, library, arts, music, live-music, theatre, comedy, circus, "
    "sports, running, free, municipal, entertainment, talks-&-lectures, classes-&-lessons, exercise. Classes (gym/pool/fitness, lessons, "
    "workshops, courses) are usually paid, so they're only included when the listing explicitly says they're "
    "free. Returns at most 40 events spread across the days in the range, "
    "plus the total that matched.",
    {
        "type": "object",
        "properties": {
            "start_date": {"type": "string", "description": "First day, YYYY-MM-DD (local time)."},
            "end_date": {"type": "string", "description": "Last day, inclusive, YYYY-MM-DD. Same as start_date for one day."},
            "categories": {"type": "string", "description": "Optional comma-separated categories; any match."},
            "query": {"type": "string", "description": "Optional text search (title/description/venue), e.g. 'pumpkin'."},
            "free_only": {"type": "boolean", "description": "Only events known to be free."},
        },
        "required": ["start_date", "end_date"],
    },
    "/local-events",
)

# Classes are usually paid (the Y's are member classes), and a weekend would
# otherwise be mostly "Open Gym" and "Aqua Fit". Product rule: a class is
# only shown with explicit evidence it costs nothing - never on "no price
# listed", which for a class almost always means "ask at the desk".
_CLASS_CATEGORIES = {"group-exercise", "open-gym", "gym", "pool", "swim", "fitness", "ymca", "child-care", "class", "classes-&-lessons", "exercise"}
_CLASS_TITLE_RE = re.compile(r"\b(class(es)?|lessons?|courses?|workshops?|clinics?|bootcamp)\b", re.I)
# "gluten-free", "sugar-free", "feel free", "free-throw" aren't about price.
_FREE_TEXT_RE = re.compile(
    r"(?<![-\w])(?<!feel )free\b(?!-)|\bno (cost|charge|fee)s?\b|\bcomplimentary\b|\bfree of charge\b"
    r"|\bwithout charge\b|\bat no cost\b|\$0(\.00)?\b",
    re.I,
)
_KID_CATEGORIES = {"family", "kids"}
_MAX_EVENTS = 40
_MAX_RANGE_DAYS = 31

PERSONAL_TOOL_NAMES = frozenset(_TOOLS)

PERSONAL_PROMPT = (
    " The person you're talking with is signed in, so you also have personal tools for their own children "
    "(or, for a student, themselves): to-dos, grades, schedule, announcements, teacher emails, late policies, "
    "specials, and notifications - plus local community events (find_local_events). Start with list_my_children to get student ids; if they have more than one "
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
            elif name == "find_local_events":
                data = await self._find_local_events(arguments)
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

    async def _find_local_events(self, args: dict[str, Any]) -> Any:
        try:
            first = date.fromisoformat(str(args.get("start_date", "")))
            last = date.fromisoformat(str(args.get("end_date", "")))
        except ValueError:
            return {"error": "start_date and end_date must be YYYY-MM-DD"}
        if last < first:
            first, last = last, first
        if (last - first).days >= _MAX_RANGE_DAYS:
            return {"error": f"Ask about at most {_MAX_RANGE_DAYS} days at a time"}

        categories = str(args.get("categories") or "").strip()
        params: dict[str, Any] = {
            "start": datetime.combine(first, time.min, ET).isoformat(),
            "end": datetime.combine(last, time.max, ET).isoformat(),
            "limit": 1000,
        }
        if categories:
            params["categories"] = categories
        if args.get("query"):
            params["q"] = str(args["query"])[:200]
        if args.get("free_only"):
            params["is_free"] = "true"

        response = await self._client.get("/local-events", params=params)
        if response.status_code >= 400:
            return {"error": f"{response.status_code} {response.reason_phrase}", "detail": response.text[:500]}
        events = response.json()["items"]

        events = [e for e in events if not _is_class(e) or _is_explicitly_free(e)]
        matched = len(events)

        # Round-robin across days so Sunday isn't cut off by Saturday
        # morning's volume; within a day, family/kids-tagged events first.
        by_day: dict[str, list[dict]] = defaultdict(list)
        for e in events:
            by_day[datetime.fromisoformat(e["start_time"]).astimezone(ET).date().isoformat()].append(e)
        for day_events in by_day.values():
            day_events.sort(key=lambda e: not set(e["categories"]) & _KID_CATEGORIES)
        picked: list[dict] = []
        queues = [by_day[d] for d in sorted(by_day)]
        while len(picked) < _MAX_EVENTS and any(queues):
            for q in queues:
                if q and len(picked) < _MAX_EVENTS:
                    picked.append(q.pop(0))
        picked.sort(key=lambda e: e["start_time"])

        result: dict[str, Any] = {"matched": matched, "returned": len(picked), "items": [_compact_event(e) for e in picked]}
        if matched > len(picked):
            result["note"] = "More events matched than shown - narrow by day, category, or a search term to see others."
        return result


def _is_class(e: dict) -> bool:
    return bool(set(e["categories"]) & _CLASS_CATEGORIES) or bool(_CLASS_TITLE_RE.search(e["title"]))


def _is_explicitly_free(e: dict) -> bool:
    if e["is_free"] or (e["price_max"] is not None and float(e["price_max"]) == 0):
        return True
    return bool(_FREE_TEXT_RE.search(f"{e['title']} {e['description'] or ''}"))


def _compact_event(e: dict) -> dict:
    start = datetime.fromisoformat(e["start_time"]).astimezone(ET)
    out: dict[str, Any] = {
        "title": e["title"],
        "when": start.strftime("%a %b %-d") + ("" if e["all_day"] else start.strftime(" %-I:%M %p")),
        "where": e["venue_name"] or e["venue_address"],
        "categories": e["categories"],
        "url": e["url"],
    }
    if e["end_time"] and not e["all_day"]:
        end = datetime.fromisoformat(e["end_time"]).astimezone(ET)
        out["ends"] = end.strftime("%-I:%M %p") if end.date() == start.date() else end.strftime("%a %b %-d")
    if e["is_free"]:
        out["price"] = "free"
    elif e["price_min"] is not None:
        out["price"] = f"${e['price_min']:g}" + (f"-${e['price_max']:g}" if e["price_max"] and e["price_max"] != e["price_min"] else "")
    if e["description"]:
        out["description"] = e["description"][:240]
    return out
