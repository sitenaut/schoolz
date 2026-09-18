"""Kids view v2: the pure rules behind the parent/student coursework dashboard
(docs/KIDS_VIEW_V2_DESIGN.md). No DB or network access here - routers/bucket3.py
loads rows and passes them in - so every rule (what counts as Missing, which
single item is "next", which staff email a teacher name resolves to) is
unit-testable and re-derivable by reading this one file. That predictability is
the point: a parent and a child with ADHD both need to trust why the page
picked what it picked.
"""
from __future__ import annotations

import re
from datetime import datetime, time, timedelta
from zoneinfo import ZoneInfo

from services.bell_schedule import current_period
from services.bucket3_extract import course_codes_from_name, normalize_title

LOCAL_TZ = ZoneInfo("America/New_York")

# Classroom's own words for "the student already handled this" - confirmed
# real in classwork/stream captures: "Completed" (card label), "Turned in",
# "Graded". "Returned"/"Done late"/"Turned in late" are Classroom UI wording
# not yet seen in a capture; they mean the same thing, so they're accepted.
DONE_STATUSES = {"Completed", "Turned in", "Graded", "Returned", "Done late", "Turned in late"}
# Reference content, never a to-do: materials and announcements.
REFERENCE_TYPES = {"material", "announcement"}


def parse_clock(value: str | None) -> time | None:
    """"7:30 AM" -> time(7, 30). Genesis daily blocks use 12-hour labels."""
    if not value:
        return None
    m = re.match(r"^\s*(\d{1,2}):(\d{2})\s*([AaPp][Mm])\s*$", value)
    if not m:
        return None
    hour = int(m.group(1)) % 12
    if m.group(3).lower() == "pm":
        hour += 12
    return time(hour, int(m.group(2)))


def right_now(blocks: list, bell_periods: dict | None, now: datetime) -> dict:
    """What's happening in this child's day right now, from their own captured
    Genesis daily schedule (ChildScheduleBlock rows, source="daily").

    Reuses bell_schedule.current_period - the same arithmetic the Today page
    runs against a school's bell table - by handing it this child's blocks as
    a one-variant table, rather than a second "what period is it" routine.
    `period_number` maps a block (Genesis's A-G rotation letters) to the
    school's own numbered period by matching start times against the
    school's regular bell table - confirmed real at East: block A starts
    07:30 = period 1, block F 12:32 = period 5.

    A schedule captured for a different day is returned with stale=True and no
    current/next - never shown as if it were today's (a stale list the parent
    trusts is worse than an honest "not captured today")."""
    now = now.astimezone(LOCAL_TZ)
    today_key = now.strftime("%m/%d")

    todays = [b for b in blocks if b.schedule_date == today_key]
    stale = False
    shown = todays
    if not todays and blocks:
        floor = datetime.min.replace(tzinfo=LOCAL_TZ)
        latest = max(blocks, key=lambda b: getattr(b, "updated_at", None) or floor)
        shown = [b for b in blocks if b.schedule_date == latest.schedule_date]
        stale = True

    period_numbers = {p["start"]: p["name"] for p in (bell_periods or {}).get("regular") or []}

    rows = []
    for b in shown:
        start, end = parse_clock(b.time_start), parse_clock(b.time_end)
        if start and end:
            rows.append((start, end, b))
    rows.sort(key=lambda r: r[0])

    table = {"regular": [{"name": b.period, "start": s.strftime("%H:%M"), "end": e.strftime("%H:%M")} for s, e, b in rows]}
    cur = None if stale else current_period(table, "open", now)

    blocks_out = []
    current = None
    for s, e, b in rows:
        is_current = bool(cur and cur["name"] == b.period)
        item = {
            "period": b.period,
            "period_number": period_numbers.get(s.strftime("%H:%M")),
            "course_name": b.course_name,
            "teacher": b.teacher,
            "room": b.room,
            "time_start": b.time_start,
            "time_end": b.time_end,
            "minutes_in": cur["minutes_in"] if is_current else None,
            "minutes_left": cur["minutes_left"] if is_current else None,
            "is_current": is_current,
        }
        blocks_out.append(item)
        if is_current:
            current = item

    nxt = None
    school_day_over = False
    if not stale and rows:
        now_t = now.time()
        upcoming = [item for (s, _e, _b), item in zip(rows, blocks_out) if s > now_t]
        nxt = upcoming[0] if upcoming else None
        school_day_over = now_t >= rows[-1][1]

    return {
        "schedule_date": shown[0].schedule_date if shown else None,
        "stale": stale,
        "school_day_over": school_day_over,
        "current": current,
        "next": nxt,
        "blocks": blocks_out,
    }


def resolve_done(override: bool | None, classroom_status: str | None, has_real_grade: bool) -> tuple[bool, str | None]:
    """(done, source). A person's explicit mark in schoolz wins in both
    directions - unchecking something Classroom calls "Completed" is a real
    signal too (Classroom's status can be wrong or lag). Otherwise Classroom's
    own status, then a real (not Missing/Exempt) Genesis score."""
    if override is not None:
        return override, ("marked" if override else None)
    if classroom_status in DONE_STATUSES:
        return True, "classroom"
    if has_real_grade:
        return True, "genesis"
    return False, None


def todo_category(item_type: str, due_date: str | None, done: bool, today_iso: str) -> str:
    """"done" | "missing" | "due" | "no_due_date". Missing is always derived
    (past due + not done): Classroom's own captured text never says "Missing"
    (confirmed across every real capture so far)."""
    if done:
        return "done"
    if item_type in REFERENCE_TYPES or not due_date:
        return "no_due_date"
    return "missing" if due_date < today_iso else "due"


def in_current_marking_period(category: str, due_date: str | None, mp_start: str | None) -> bool:
    """Work from a marking period that already ended no longer counts against
    the current one - so Missing/Done from before the current MP's start are
    dropped from the to-do list and progress (explicit product rule). Upcoming
    work is always kept, and nothing is filtered when no MP is known."""
    if not mp_start or category in ("due", "no_due_date"):
        return True
    return bool(due_date) and due_date >= mp_start


def progress(items: list[dict]) -> dict:
    """Counts only dated, current-MP items (callers pre-filter) - the one bar
    that answers "how close am I to caught up"."""
    done = sum(1 for i in items if i["category"] == "done" and i.get("due_date"))
    missing = sum(1 for i in items if i["category"] == "missing")
    due = sum(1 for i in items if i["category"] == "due")
    total = done + missing + due
    return {
        "done": done,
        "missing": missing,
        "due": due,
        "total": total,
        "percent": round(done * 100 / total) if total else None,
    }


def pick_next_action(items: list[dict]) -> dict | None:
    """One thing to work on, chosen by a fixed rule anyone can re-derive:
    the oldest Missing item first, otherwise whatever is due soonest. Never
    an AI or personalized ranking."""
    missing = sorted((i for i in items if i["category"] == "missing"), key=lambda i: (i["due_date"], i["title"]))
    if missing:
        return missing[0]
    due = sorted((i for i in items if i["category"] == "due"), key=lambda i: (i["due_date"], i["title"]))
    return due[0] if due else None


_HONORIFIC_RE = re.compile(r"^(mr|mrs|ms|miss|mx|dr|herr|frau|sra|sr|mme|mlle)\.?\s+", re.I)
_SPLIT_NAMES_RE = re.compile(r"\s*(?:/|;|&|\band\b)\s*", re.I)


def _norm_name(value: str) -> str:
    return re.sub(r"[^a-z]", "", value.lower())


def name_parts(raw: str | None) -> list[tuple[str | None, str]]:
    """Every (first, last) person in a teacher field. Handles the real shapes:
    Genesis "Rouen, Gregory" and co-taught "Borrelli/Squazzo", Classroom's
    "Anthony Maniscalco", and "Mr. Maniscalco"."""
    if not raw:
        return []
    parts: list[tuple[str | None, str]] = []
    for chunk in _SPLIT_NAMES_RE.split(raw.strip()):
        chunk = chunk.strip()
        if not chunk:
            continue
        if "," in chunk:
            last, rest = chunk.split(",", 1)
            first_tokens = rest.strip().split()
            first = first_tokens[0] if first_tokens else None
        else:
            tokens = _HONORIFIC_RE.sub("", chunk).split()
            if not tokens:
                continue
            last = tokens[-1]
            first = tokens[0] if len(tokens) > 1 else None
        last_n = _norm_name(last)
        if last_n:
            parts.append((_norm_name(first) if first else None, last_n))
    return parts


def match_teacher_emails(raw: str | None, staff: list[tuple[str, str | None]]) -> list[str]:
    """Resolve a teacher field to staff-directory emails (StaffMember rows for
    the child's own school). Matches on last name, narrowed by first name when
    one is known; an ambiguous match (two staff share the name and nothing
    narrows it) resolves to nothing rather than a guess - a wrong teacher's
    email is worse than no link."""
    if not raw:
        return []
    index = []
    for full_name, email in staff:
        parsed = name_parts(full_name)
        if email and parsed:
            index.append((parsed[0], email.strip()))
    emails: list[str] = []
    for first, last in name_parts(raw):
        candidates = [(f, e) for (f, l), e in index if l == last]
        if first:
            narrowed = [(f, e) for f, e in candidates if f and (f.startswith(first) or first.startswith(f))]
            if narrowed:
                candidates = narrowed
        unique = sorted({e.lower() for _, e in candidates})
        if len(unique) == 1 and unique[0] not in emails:
            emails.append(unique[0])
    return emails


def course_key(course_name: str | None, course_external_id: str | None) -> tuple[str, str]:
    """The class identity AssignmentSuggestion is shared under. Prefers the
    district's own course/section code (the same pair Genesis uses, embedded
    in Classroom's course name - see course_codes_from_name), so every student
    in a section shares one cached suggestion; falls back to Classroom's course
    slug, then the normalized name."""
    codes = course_codes_from_name(course_name or "")
    if codes:
        return codes[0]
    if course_external_id:
        return f"slug:{course_external_id}", ""
    return f"name:{normalize_title(course_name or 'unknown')}", ""


def course_progress(items: list[dict], grade_entries: list, course_grades: list, today_iso: str) -> list[dict]:
    """Per-class rollup for the student's "how am I doing in each class" view.
    `items` are current-MP to-do dicts (with course_key/course_name/category/
    due_date/teacher fields); `grade_entries`/`course_grades` are current-MP
    Genesis rows. `low_grade_entries` flags scores under 50% only - the
    makeup-to-70% rule is teacher/district policy this app has no source for,
    so it's surfaced as "ask about makeup work", never calculated."""
    soon = (datetime.fromisoformat(today_iso) + timedelta(days=7)).date().isoformat()
    courses: dict[tuple[str, str], dict] = {}

    def bucket(key: tuple[str, str], name: str | None) -> dict:
        if key not in courses:
            courses[key] = {
                "course_key": f"{key[0]}-{key[1]}" if key[1] else key[0],
                "course_name": name,
                "grade_percent": None,
                "marking_period": None,
                "total": 0,
                "done": 0,
                "missing": 0,
                "due_soon": 0,
                "completion_pct": None,
                "low_grade_entries": [],
                "teacher_name": None,
                "teacher_emails": [],
            }
        elif name and not courses[key]["course_name"]:
            courses[key]["course_name"] = name
        return courses[key]

    for i in items:
        if i["category"] == "no_due_date":
            continue
        c = bucket(i["course_key"], i.get("course_name"))
        if i["category"] == "done" and not i.get("due_date"):
            continue
        c["total"] += 1
        if i["category"] == "done":
            c["done"] += 1
        elif i["category"] == "missing":
            c["missing"] += 1
        elif i["category"] == "due" and i["due_date"] <= soon:
            c["due_soon"] += 1
        if i.get("teacher_name") and not c["teacher_name"]:
            c["teacher_name"] = i["teacher_name"]
            c["teacher_emails"] = i.get("teacher_emails") or []

    graded_courses = {(e.course_code, e.course_section) for e in grade_entries}
    for g in course_grades:
        c = bucket((g.course_code, g.course_section), g.course_name)
        # Genesis shows "0.00%" for a class with nothing graded yet - that's
        # "no grade", not a failing one.
        c["grade_percent"] = g.grade_percent if (g.course_code, g.course_section) in graded_courses else None
        c["marking_period"] = g.marking_period

    for e in grade_entries:
        if e.percent is not None and e.percent < 50:
            c = bucket((e.course_code, e.course_section), e.course_name)
            c["low_grade_entries"].append({"title": e.title, "percent": e.percent})

    out = []
    for c in courses.values():
        if c["total"]:
            c["completion_pct"] = round(c["done"] * 100 / c["total"])
        if not c["course_name"]:
            c["course_name"] = f"Course {c['course_key']}"
        out.append(c)
    out.sort(key=lambda c: (-c["missing"], -len(c["low_grade_entries"]), c["course_name"]))
    return out
