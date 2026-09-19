"""Extraction layer for Backpack Capture imports (bucket 3: a child's own
Classroom/Genesis data - see the sibling `backpack-capture` repo, which
produces the reduced-text capture envelopes this module parses).

This is a straight port of that repo's `viewer/parse.js` prototype logic
into Python, validated against a real capture export before being wired
into a router - same "verify one real capture first" rule the extension's
own adapters were built under. Every regex/heuristic here has a comment
citing what real capture text it was built against.

Deliberately kept separate from every other `services/*.py` module: those
all process *public*, admin-managed data (Smore newsletters, district
calendars, staff rosters). This module processes a guardian's own
personal, credentialed capture of their child's account - never shared,
never scheduled, only ever triggered by that guardian uploading their own
export. See CLAUDE.md's "Access model" section.
"""
from __future__ import annotations

import base64
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

# ---- page classification --------------------------------------------------


@dataclass
class PageKind:
    pattern: str
    description: str


def classify_page(adapter: str, source_url: str) -> PageKind:
    """Normalizes a capture's URL to a stable pattern key so the page-map
    catalog groups "the same kind of page" regardless of which
    course/student it was for. Unrecognized shapes fall into a generic
    bucket rather than being dropped - the whole point of the page map is
    to surface what ISN'T recognized yet."""
    if adapter == "classroom":
        # The extension follows every real detail-page anchor it finds on a
        # Classwork/Stream page (backpack-capture's detailStepsFrom), so
        # these arrive routinely and shouldn't sit in the "unrecognized"
        # bucket the catalog exists to flag.
        if re.search(r"/u/\d+/c/[\w-]+/a/[\w-]+/details", source_url):
            return PageKind("classroom:/u/N/c/:courseId/a/:id/details", "Classroom: Assignment detail")
        if re.search(r"/u/\d+/c/[\w-]+/m/[\w-]+/details", source_url):
            return PageKind("classroom:/u/N/c/:courseId/m/:id/details", "Classroom: Material detail")
        if re.search(r"/u/\d+/w/[\w-]+/t/all", source_url):
            return PageKind("classroom:/u/N/w/:courseId/t/all", "Classroom: Classwork tab")
        if re.search(r"/u/\d+/c/[\w-]+$", source_url):
            return PageKind("classroom:/u/N/c/:courseId", "Classroom: Class stream")
        if re.search(r"/u/\d+/h(/st)?(\?|$)", source_url) or source_url.endswith("/h/st"):
            return PageKind("classroom:/u/N/h", "Classroom: Home / To-do")
        return PageKind("classroom:other", "Classroom: unrecognized page")
    if adapter == "genesis":
        if "tab3=coursesummary" in source_url:
            return PageKind("genesis:gradebook-course", "Genesis: Course grade detail")
        if "tab3=weeklysummary" in source_url:
            return PageKind("genesis:gradebook-weekly", "Genesis: Grade summary (all courses)")
        if "tab2=studentsummary" in source_url:
            return PageKind("genesis:studentsummary", "Genesis: Student summary")
        return PageKind("genesis:other", "Genesis: unrecognized page")
    return PageKind(f"{adapter}:other", "Unrecognized adapter")


# ---- Classroom extraction --------------------------------------------------


@dataclass
class CourseMap:
    by_slug: dict[str, str] = field(default_factory=dict)
    by_numeric: dict[str, str] = field(default_factory=dict)
    # (course_code, section) -> name, e.g. ("331", "10") -> "F: CHEM-1A 331-10".
    # This is the cross-source link to Genesis: see course_codes_from_name.
    by_code: dict[tuple[str, str], str] = field(default_factory=dict)


# Every Classroom page's nav menu lists every enrolled course, keyed both
# by its URL slug (base64-ish, from /c/<slug>) and its numeric data-id -
# confirmed real, both appear on the same menuitem line:
# "[aria-label] ENG 2A Block B (26-27) 121-1 (role=menuitem)
#  (href: /u/2/c/ODc2NDQ0NzExNTM3) (data-id: 876444711537)"
_COURSE_MENU_RE = re.compile(
    # Names can contain parentheses - "ENG 2A Block B (26-27) 121-1" is real.
    r"\[aria-label\] (.+?) \(role=menuitem\) \(href: /u/\d+/c/([\w-]+)\)(?: \(data-id: (\d+)\))?"
)

# A trailing "<code>-<section>" in a Classroom course name (e.g. "F:
# CHEM-1A 331-10", "INTERMEDIATE GERMAN I H FY Period G 2026-27
# 682A-2, 682-2") is this district's own course/section code - confirmed
# real: it's *exactly* what Genesis's gradebook URLs carry as
# courseCode/courseSection (331/10, 682/2). This is the deterministic
# cross-source link the audit is built on - no fuzzy name matching needed
# at the course level. A name can embed more than one such pair (an
# academic-year range like "2026-27" matches the same digit-dash-digit
# shape) - excluded by range, since every real course code seen is well
# outside 2000-2099.
_COURSE_CODE_RE = re.compile(r"\b(\d{2,4})-(\d{1,2})\b")


def course_codes_from_name(name: str) -> list[tuple[str, str]]:
    codes = []
    for code, section in _COURSE_CODE_RE.findall(name):
        if 2000 <= int(code) <= 2099:
            continue  # an academic-year range (e.g. "2026-27"), not a course code
        if len(code) == 2 and len(section) == 2 and int(section) == (int(code) + 1) % 100:
            continue  # a short year range - "ENG 2A Block B (26-27) 121-1" is real
        codes.append((code, section))
    return codes


def extract_course_map(text: str) -> CourseMap:
    cm = CourseMap()
    for m in _COURSE_MENU_RE.finditer(text):
        name = m.group(1).strip()
        cm.by_slug[m.group(2)] = name
        if m.group(3):
            cm.by_numeric[m.group(3)] = name
        for code, section in course_codes_from_name(name):
            cm.by_code[(code, section)] = name
    return cm


# "Google Account: Sample Student  \n(9999999@chclc.org)" - the aria-label
# value itself contains an embedded newline before the parenthesized
# email, confirmed real (values shown here are placeholders; see test
# fixtures). The email's local part equals the Genesis studentid for this
# district's student logins (confirmed real: both the same numeric id) -
# the link between a Classroom capture and a Genesis student.
_ACCOUNT_RE = re.compile(r"Google Account: ([^\n(]+)\s*\n?\(([\w.+-]+@[\w.-]+)\)")


def extract_classroom_account(text: str) -> tuple[str, str] | None:
    m = _ACCOUNT_RE.search(text)
    if not m:
        return None
    return m.group(1).strip(), m.group(2)


def classroom_account_student_id(text: str) -> str | None:
    """Best-effort identity guard for Classroom captures, mirroring
    genesis_student_id_from_url - a family plausibly has more than one
    child's Classroom account captured across a single export (confirmed
    real families in this district: 4+ kids under one guardian, switchable
    via Google's own account picker), and nothing about a Classroom
    capture's envelope says which child it's for the way Genesis's
    studentid URL param does. Only returns a value when the logged-in
    account's email local part is purely numeric (this district's
    student-login convention, confirmed real: "9999999@chclc.org" for
    Genesis studentid 9999999, placeholder values - see test fixtures) - a
    non-numeric local part (most districts)
    means this signal isn't available, and the caller should not block
    on it rather than guess."""
    account = extract_classroom_account(text)
    if not account:
        return None
    local_part = account[1].split("@")[0]
    return local_part if local_part.isdigit() else None


def _course_slug_from_url(url: str) -> str | None:
    m = re.search(r"/w/([\w-]+)/t/all", url) or re.search(r"/c/([\w-]+)$", url)
    return m.group(1) if m else None


@dataclass
class WorkItem:
    external_uid: str
    title: str
    item_type: str
    due_raw: str | None
    course_id: str | None
    course_name: str | None
    link: str | None
    status: str | None = None
    teacher_name: str | None = None
    posted_raw: str | None = None
    body: str | None = None


_SHAPE_A_RE = re.compile(r"^\[aria-label\] (Assignment|Material|Announcement): (.+)$")
_HREF_RE = re.compile(r"\(href: (\S+)\)")
_STREAM_ID_RE = re.compile(r"\(data-stream-item-id: (\d+)\)")
_PAREN_RE = re.compile(r"\s*\([^)]*\)")
_DUE_SUFFIX_RE = re.compile(r"^(.*?),\s*due\s+(.+)$", re.I)
_BUTTON_RE = re.compile(r"^\[aria-label\] (.+) \(role=button\)$")
_TYPE_LINE_RE = re.compile(r"^(Assignment|Material|Quiz|Question)$")
_DUE_LINE_RE = re.compile(r"^Due (.+)$")
# "Kenneth Smith posted a new assignment: Pre-Test Google Form" and
# "Posted Sep 11" - both confirmed real on a class's feed cards.
_POSTED_BY_RE = re.compile(r"^(.+?) posted a new (?:assignment|material|question|quiz assignment): ")
_POSTED_LINE_RE = re.compile(r"^Posted (.+)$")
_ITEM_ID_IN_HREF_RE = re.compile(r"/c/[\w-]+/(?:a|m|p|q|sa|mc)/([\w-]+)/details")
# Classroom's own per-item status words, most informative first. Confirmed
# real: "Completed" (card label, grid and feed), "Graded" and "Turned in"
# (submission chip on feed cards). A card can show both "Completed" and
# "Graded"; the more specific one is kept.
_STATUS_PRIORITY = ["Graded", "Returned", "Turned in late", "Turned in", "Done late", "Completed", "Missing"]


def _better_status(current: str | None, candidate: str) -> str | None:
    if candidate not in _STATUS_PRIORITY:
        return current
    if current is None or _STATUS_PRIORITY.index(candidate) < _STATUS_PRIORITY.index(current):
        return candidate
    return current


def _stream_id_from_href(href: str | None) -> str | None:
    """Classroom's /a/<id>/details path segment is the numeric stream-item id,
    base64-encoded - confirmed real: "ODg0NjAzNzc3NzY1" decodes to
    "884603777765", the same id the classwork grid carries as
    data-stream-item-id. Decoding it gives both page layouts one shared
    identity; before this, the feed card fell back to a title hash and the
    same assignment showed up twice (visible as doubled rows in the audit)."""
    m = _ITEM_ID_IN_HREF_RE.search(href or "")
    if not m:
        return None
    segment = m.group(1)
    try:
        decoded = base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("ascii")
    except (ValueError, UnicodeDecodeError):
        return None
    return decoded if decoded.isdigit() else None


# Each class page Classroom renders is a view whose root names its class:
# "(data-p: %.@."ODcyNDkxNDc4MTk4"]) ...". Confirmed real: Classroom keeps
# the previously opened class's view in the DOM, so a capture under one
# class's URL also held the previous class's Classwork list - trusting the
# URL filed every class's work under the class captured after it.
_VIEW_COURSE_RE = re.compile(r'\(data-p: %\.@\."([\w-]+)"')


def _is_course_slug(segment: str) -> bool:
    try:
        return base64.urlsafe_b64decode(segment + "=" * (-len(segment) % 4)).decode("ascii").isdigit()
    except (ValueError, UnicodeDecodeError):
        return False


def _view_course_slugs(lines: list[str], fallback: str | None) -> list[str | None]:
    """The course of the innermost enclosing class view for every line."""
    current = fallback
    out = []
    for line in lines:
        m = _VIEW_COURSE_RE.search(line)
        if m and _is_course_slug(m.group(1)):
            current = m.group(1)
        out.append(current)
    return out


def _join_wrapped_labels(lines: list[str]) -> list[str]:
    """An aria-label containing a newline gets flattened across two lines
    with the "(role=button)" suffix on the second - confirmed real:
    "[aria-label] Chem-1H Class Info Assignment" / "Due = Fri-the-4th, 10:00 PM
    (role=button)". Rejoin them so the button pattern sees one line."""
    out: list[str] = []
    i = 0
    while i < len(lines):
        line = lines[i]
        if (
            line.startswith("[aria-label] ")
            and not line.rstrip().endswith(")")
            and i + 1 < len(lines)
            and lines[i + 1].endswith("(role=button)")
            and not lines[i + 1].startswith(("[", "("))
        ):
            out.append(f"{line.rstrip()} {lines[i + 1]}")
            i += 2
            continue
        out.append(line)
        i += 1
    return out


def _merge_item(items: dict[str, WorkItem], new: WorkItem) -> None:
    """The same item can appear on one page in both layouts (a feed card and
    a classwork-grid row) with different fields filled in - the feed has the
    teacher and posted date, the grid has the due date. Merge instead of
    letting whichever came last overwrite the other."""
    old = items.get(new.external_uid)
    if old is None:
        items[new.external_uid] = new
        return
    for field_name in ("due_raw", "course_id", "course_name", "link", "teacher_name", "posted_raw", "body"):
        if getattr(new, field_name) and not getattr(old, field_name):
            setattr(old, field_name, getattr(new, field_name))
    if new.status:
        old.status = _better_status(old.status, new.status)


def extract_classroom_work_items(source_url: str, text: str, course_map: CourseMap) -> list[WorkItem]:
    """Combines two distinct item shapes confirmed present in real
    captures:
      A) stream/to-do style - one label line, then a card block below it:
         "[aria-label] Assignment: Title, due Tomorrow (href: ...) ..."
         ... "Completed" ... "Kenneth Smith posted a new assignment: Title"
         ... "Posted Sep 11" ... "Graded"
      B) classwork-list style - a button label, then a type line, then
         (sometimes) a "Due <text>" line a few lines later:
         "[aria-label] Untitled Formative 817 (role=button)" ... "Assignment" ... "Due Sep 16, 9:30 AM"
    """
    lines = _join_wrapped_labels(text.split("\n"))
    view_slugs = _view_course_slugs(lines, _course_slug_from_url(source_url))
    items: dict[str, WorkItem] = {}

    for i, line in enumerate(lines):
        m = _SHAPE_A_RE.match(line)
        if not m:
            continue
        item_type = m.group(1).lower()
        rest = m.group(2)
        href_m = _HREF_RE.search(rest)
        id_m = _STREAM_ID_RE.search(rest)
        label = _PAREN_RE.sub("", rest).strip()
        due_m = _DUE_SUFFIX_RE.match(label)
        title = (due_m.group(1) if due_m else label).strip().strip('"')
        due_raw = due_m.group(2) if due_m else None
        href = href_m.group(1) if href_m else None
        slug_m = re.search(r"/c/([\w-]+)/", href) if href else None
        course_slug = slug_m.group(1) if slug_m else view_slugs[i]

        item_id = id_m.group(1) if id_m else _stream_id_from_href(href)
        if not item_id:
            # Stream cards carry the id a line or two above the label
            # (confirmed real), not on it.
            for back in range(max(0, i - 3), i):
                back_m = _STREAM_ID_RE.search(lines[back])
                if back_m:
                    item_id = back_m.group(1)

        status = teacher = posted = None
        for j in range(i + 1, min(len(lines), i + 45)):
            nxt = lines[j]
            if (
                nxt.startswith("(data-include-stream-item-materials")
                or nxt.startswith("Post by ")
                or _SHAPE_A_RE.match(nxt)
                or _BUTTON_RE.match(nxt)
            ):
                break  # the next card started
            stripped = nxt.strip()
            status = _better_status(status, stripped)
            if teacher is None:
                posted_by = _POSTED_BY_RE.match(stripped)
                if posted_by:
                    teacher = posted_by.group(1).strip()
            if posted is None:
                posted_line = _POSTED_LINE_RE.match(stripped)
                if posted_line:
                    posted = posted_line.group(1).strip()
                elif stripped == "Created" and j + 1 < len(lines):
                    posted = lines[j + 1].strip() or None

        uid = f"si:{item_id}" if item_id else f"hash:{course_slug}:{title}"
        _merge_item(
            items,
            WorkItem(
                external_uid=uid,
                title=title,
                item_type=item_type,
                due_raw=due_raw,
                course_id=course_slug,
                course_name=course_map.by_slug.get(course_slug) if course_slug else None,
                link=href,
                status=status,
                teacher_name=teacher,
                posted_raw=posted,
            ),
        )

    for i, line in enumerate(lines):
        m = _BUTTON_RE.match(line)
        if not m:
            continue
        title = m.group(1).strip()
        item_type = None
        item_id = None
        due_raw = None
        status = None
        for j in range(i + 1, min(len(lines), i + 12)):
            if _BUTTON_RE.match(lines[j]):
                break  # next item started - stop
            if item_type is None:
                tm = _TYPE_LINE_RE.match(lines[j])
                if tm:
                    item_type = tm.group(1).lower()
            if item_id is None:
                idm = _STREAM_ID_RE.search(lines[j])
                if idm:
                    item_id = idm.group(1)
            if due_raw is None:
                dm = _DUE_LINE_RE.match(lines[j])
                if dm:
                    due_raw = dm.group(1)
            status = _better_status(status, lines[j].strip())
        if item_type is None:
            continue  # not actually a work-item button (e.g. a menu button)
        row_slug = view_slugs[i]
        uid = f"si:{item_id}" if item_id else f"hash:{row_slug}:{title}"
        _merge_item(
            items,
            WorkItem(
                external_uid=uid,
                title=title,
                item_type=item_type,
                due_raw=due_raw,
                course_id=row_slug,
                course_name=course_map.by_slug.get(row_slug) if row_slug else None,
                link=f"/c/{row_slug}" if row_slug else None,
                status=status,
            ),
        )

    return list(items.values())


_POST_BY_RE = re.compile(r"^Post by (.+)$")
_ANNOUNCEMENT_OPTIONS_RE = re.compile(r"^\[aria-label\] Announcement options for (.+?)(?: \(|$)")
_ANNOUNCEMENT_END_PREFIXES = (
    "(data-is-edit-mode",
    "(data-type:",
    "No class comments",
    "Post by ",
    "(data-include-stream-item-materials",
)
_ANNOUNCEMENT_CHROME = {"more_vert", "(role=tooltip)", "More options"}


def extract_classroom_announcements(source_url: str, text: str, course_map: CourseMap) -> list[WorkItem]:
    """Teacher announcements from a class's Stream (or the feed section of its
    Classwork page). These never carry an "Announcement:" aria-label, so the
    work-item extractor never saw them. Confirmed real shape:

        (data-include-stream-item-materials: false) (data-stream-item-id: 877349388671)
        Post by Kenneth Smith
        Kenneth Smith
        Created
        Sep 3
        ...
        [aria-label] Announcement options for Course Expectations (...)
        more_vert / (role=tooltip) / More options
        <body text lines>
        (data-is-edit-mode: false) ...
    """
    lines = text.split("\n")
    view_slugs = _view_course_slugs(lines, _course_slug_from_url(source_url))
    found: dict[str, WorkItem] = {}
    for i, line in enumerate(lines):
        post_by = _POST_BY_RE.match(line.strip())
        if not post_by:
            continue
        teacher = post_by.group(1).strip()
        item_id = None
        for back in range(max(0, i - 3), i):
            back_m = _STREAM_ID_RE.search(lines[back])
            if back_m:
                item_id = back_m.group(1)

        posted = None
        options_idx = None
        label = None
        for j in range(i + 1, min(len(lines), i + 30)):
            stripped = lines[j].strip()
            if _POST_BY_RE.match(stripped):
                break
            if stripped == "Created" and posted is None and j + 1 < len(lines):
                posted = lines[j + 1].strip() or None
            options = _ANNOUNCEMENT_OPTIONS_RE.match(stripped)
            if options:
                options_idx = j
                label = options.group(1).rstrip("…").strip() or None
                break
        if options_idx is None:
            continue  # a "Post by" that isn't an announcement card

        start = options_idx + 1
        while start < len(lines) and lines[start].strip() in _ANNOUNCEMENT_CHROME:
            start += 1
        body_lines = []
        for k in range(start, min(len(lines), start + 80)):
            stripped = lines[k].strip()
            if stripped.startswith(_ANNOUNCEMENT_END_PREFIXES):
                break
            if not stripped or stripped.startswith("(") or stripped.startswith("[aria-label]"):
                continue
            body_lines.append(stripped)

        body = "\n".join(body_lines) or None
        title = label or (body_lines[0][:80] if body_lines else "Announcement")
        slug = view_slugs[i]
        uid = f"si:{item_id}" if item_id else f"hash:{slug}:announcement:{title}:{posted}"
        found[uid] = WorkItem(
            external_uid=uid,
            title=title,
            item_type="announcement",
            due_raw=None,
            course_id=slug,
            course_name=course_map.by_slug.get(slug) if slug else None,
            link=f"/c/{slug}" if slug else None,
            teacher_name=teacher,
            posted_raw=posted,
            body=body,
        )
    return list(found.values())


# ---- Genesis extraction ----------------------------------------------------


@dataclass
class GenesisIdentity:
    first_name: str
    last_name: str
    grade: str
    school: str
    student_id: str
    state_id: str


# "Sample\nStudent\nGrade:\n10\nCherry Hill High School East\nStudent ID:\n
# 9999999\nState ID:\n1111111111" - confirmed real shape (values shown here
# are placeholders; see test fixtures), one field per line.
_IDENTITY_RE = re.compile(
    r"(\w+)\n(\w+)\nGrade:\n(\d+)\n([^\n]+)\nStudent ID:\n(\d+)\nState ID:\n(\d+)"
)


def extract_genesis_identity(text: str) -> GenesisIdentity | None:
    m = _IDENTITY_RE.search(text)
    if not m:
        return None
    return GenesisIdentity(
        first_name=m.group(1), last_name=m.group(2), grade=m.group(3),
        school=m.group(4), student_id=m.group(5), state_id=m.group(6),
    )


def extract_genesis_cycle(text: str) -> str | None:
    m = re.search(r"Today's Cycle:\n(\S+)", text)
    return m.group(1) if m else None


@dataclass
class DailyBlock:
    period: str
    time_start: str | None
    time_end: str | None
    course: str
    teacher: str | None
    room: str | None
    term: str | None


_DAILY_HEADER_RE = re.compile(r"(\d+) Day Schedule \((\d{2}/\d{2})\)")


def extract_genesis_daily_blocks(text: str) -> tuple[str, list[DailyBlock]] | None:
    """Daily View: "<N> Day Schedule (MM/DD)" then repeating period blocks
    until "Bus Info". A block is period/time/course/[teacher]/room - the
    teacher line is absent for non-class periods like lunch (confirmed
    real: "L2"/lunch has no teacher line, room follows the course name
    directly), so presence of a leading "Room:" is checked rather than
    assuming a fixed line count per block."""
    header_m = _DAILY_HEADER_RE.search(text)
    if not header_m:
        return None
    lines = [l for l in text[header_m.end():].split("\n") if l.strip() != ""]
    blocks: list[DailyBlock] = []
    i = 0
    while i < len(lines) and lines[i] != "Bus Info":
        period = lines[i]
        if not re.match(r"^[A-Za-z0-9]{1,3}$", period):
            break  # reached the end of the schedule section
        i += 1
        time_range = lines[i] if i < len(lines) else ""
        i += 1
        time_m = re.match(r"^(.+?) - (.+)$", time_range)
        course = lines[i] if i < len(lines) else ""
        i += 1
        teacher = None
        if i < len(lines) and not lines[i].startswith("Room:"):
            teacher = lines[i]
            i += 1
        room_line = lines[i] if i < len(lines) else ""
        i += 1
        room_m = re.match(r"^Room:\s*(\S+)\s*(.*)$", room_line)
        blocks.append(
            DailyBlock(
                period=period,
                time_start=time_m.group(1) if time_m else None,
                time_end=time_m.group(2) if time_m else None,
                course=course,
                teacher=teacher,
                room=room_m.group(1) if room_m else None,
                term=room_m.group(2) if room_m else None,
            )
        )
    return header_m.group(2), blocks


@dataclass
class ListBlock:
    period: str
    course: str
    term: str | None
    teacher: str | None
    room: str | None
    days: str | None


def genesis_student_id_from_url(url: str) -> str | None:
    """Every Genesis URL carries `studentid=` as a query param - a
    universal identity guard rail, unlike extract_genesis_identity's
    page-body parse, which only matches the student-summary page's
    specific header shape and returns None on gradebook pages (confirmed
    real: those have "Grade:" text from an assignment's own score, but no
    "Student ID:" block at all)."""
    m = re.search(r"studentid=(\d+)", url)
    return m.group(1) if m else None


def genesis_course_code_from_url(url: str) -> tuple[str, str] | None:
    m = re.search(r"courseCode=(\d+)&courseSection=(\d+)", url)
    return (m.group(1), m.group(2)) if m else None


@dataclass
class GenesisGradeEntry:
    weekday_date: str  # "Mon 9/14"
    title: str
    description: str | None
    category: str | None
    score_earned: float | None
    score_possible: float | None
    percent: float | None
    status: str | None  # Exempt/Missing/Incomplete/Absent/Late, if flagged
    updated: bool


@dataclass
class GenesisCourseGradeSheet:
    marking_period: str | None
    marking_period_grade_pct: float | None
    last_grade_posted: str | None
    entries: list[GenesisGradeEntry]


_ENTRY_START_RE = re.compile(r"^(Mon|Tue|Wed|Thu|Fri|Sat|Sun)$")
_ENTRY_DATE_RE = re.compile(r"^\d{1,2}/\d{1,2}$")
_GRADE_SCORE_RE = re.compile(r"^(\d+(?:\.\d+)?)\s*/\s*(\d+(?:\.\d+)?)$")
_GRADE_PERCENT_RE = re.compile(r"^(\d+(?:\.\d+)?)%$")
_GRADE_WEIGHT_RE = re.compile(r"^x(\d+(?:\.\d+)?)$")
_GRADE_PTS_ONLY_RE = re.compile(r"^Assignment Pts: (\d+(?:\.\d+)?)$")
_GRADE_STATUS_WORDS = {"Exempt", "Missing", "Incomplete", "Absent", "Late"}


def extract_genesis_course_grades(text: str) -> GenesisCourseGradeSheet | None:
    """Parses a Genesis "Course Summary" gradebook page (per-course,
    per-marking-period assignment grades) - confirmed real structure, one
    entry per assignment:

        Mon
        9/14
        Close
        Reading Quiz (Informational Texts)          <- title
        Syllabus + The Pros and Cons of Youth Sports  <- description (optional)
        Minor Assessments                             <- category
        Reading Quiz (Informational Texts)            <- title repeated
        8 / 12
        66.70%

    Whether a description line is present varies per entry (confirmed:
    some entries have one, some don't), so instead of assuming a fixed
    line count, the parser finds where the title repeats and treats
    everything between the first title and that repeat as
    description+category (category is always the line immediately before
    the repeat). Ungraded/exempt entries carry a status word
    (Exempt/Missing/...) and "Assignment Pts: N" instead of "N / M"."""
    mp_m = re.search(r"Marking Period (\d+) Grade:\n([\d.]+)%", text)
    posted_m = re.search(r"Last grade posted on (\S+)", text)

    start = text.find("Due\nAssignment\nGrade\n")
    if start == -1:
        return None
    end_m = re.search(r"\nAssignments graded as\b", text[start:])
    section = text[start : start + end_m.start()] if end_m else text[start:]
    lines = [l for l in section.split("\n") if l.strip() != ""]

    starts = [
        i
        for i in range(len(lines) - 2)
        if _ENTRY_START_RE.match(lines[i]) and _ENTRY_DATE_RE.match(lines[i + 1]) and lines[i + 2] == "Close"
    ]

    entries: list[GenesisGradeEntry] = []
    for k, idx in enumerate(starts):
        block_end = starts[k + 1] if k + 1 < len(starts) else len(lines)
        block = lines[idx + 3 : block_end]
        if not block:
            continue
        title = block[0]
        rest = block[1:]

        repeat_j = next((j for j, l in enumerate(rest) if l == title), None)
        category = rest[repeat_j - 1] if repeat_j is not None and repeat_j >= 1 else None
        description = "\n".join(rest[: repeat_j - 1]) if repeat_j is not None and repeat_j >= 2 else None
        tail = rest[repeat_j + 1 :] if repeat_j is not None else rest

        score_earned = score_possible = percent = status = None
        updated = False
        for l in tail:
            if l == "Updated":
                updated = True
            elif l in _GRADE_STATUS_WORDS:
                status = l
            elif _GRADE_SCORE_RE.match(l):
                m = _GRADE_SCORE_RE.match(l)
                score_earned, score_possible = float(m.group(1)), float(m.group(2))
            elif _GRADE_PERCENT_RE.match(l) and score_earned is not None:
                percent = float(_GRADE_PERCENT_RE.match(l).group(1))
            elif _GRADE_PTS_ONLY_RE.match(l):
                score_possible = float(_GRADE_PTS_ONLY_RE.match(l).group(1))

        entries.append(
            GenesisGradeEntry(
                weekday_date=f"{lines[idx]} {lines[idx + 1]}",
                title=title,
                description=description,
                category=category,
                score_earned=score_earned,
                score_possible=score_possible,
                percent=percent,
                status=status,
                updated=updated,
            )
        )

    return GenesisCourseGradeSheet(
        marking_period=f"MP{mp_m.group(1)}" if mp_m else None,
        marking_period_grade_pct=float(mp_m.group(2)) if mp_m else None,
        last_grade_posted=posted_m.group(1) if posted_m else None,
        entries=entries,
    )


@dataclass
class MarkingPeriodRange:
    label: str
    start_date: str  # ISO
    end_date: str  # ISO


# "MP1\n9/02 to 11/10\nMP2\n11/11 to 1/27\n..." - confirmed real on the
# Genesis "Grade Summary" (weeklysummary) page, repeated identically in
# every course's block on that page (each course shows the same
# district-wide MP calendar) - the first occurrence of each label is kept,
# later repeats are duplicates, not new data.
_MP_RANGE_RE = re.compile(r"MP(\d)\n(\d{1,2})/(\d{1,2}) to (\d{1,2})/(\d{1,2})")


def extract_genesis_marking_periods(text: str, captured_at: datetime) -> list[MarkingPeriodRange]:
    """Resolves each marking period's bare "M/D to M/D" range (no year) to
    real dates using the same school-year-boundary logic as
    resolve_due_date: MP1 starts in the calendar year the school year
    itself started, and the year rolls forward each time a later MP's
    start month is earlier than the previous one's (Dec/Jan-crossing
    marking periods, confirmed real: MP2 "11/11 to 1/27")."""
    anchor = captured_at.date() if isinstance(captured_at, datetime) else captured_at
    year = anchor.year if anchor.month >= 7 else anchor.year - 1
    seen: dict[str, MarkingPeriodRange] = {}
    prev_start_month: int | None = None
    for m in _MP_RANGE_RE.finditer(text):
        label = f"MP{m.group(1)}"
        if label in seen:
            continue
        start_month, start_day, end_month, end_day = (int(m.group(i)) for i in (2, 3, 4, 5))
        if prev_start_month is not None and start_month < prev_start_month:
            year += 1
        end_year = year if end_month >= start_month else year + 1
        seen[label] = MarkingPeriodRange(
            label=label,
            start_date=date(year, start_month, start_day).isoformat(),
            end_date=date(end_year, end_month, end_day).isoformat(),
        )
        prev_start_month = start_month
    return [seen[f"MP{i}"] for i in range(1, 5) if f"MP{i}" in seen]


_NORMALIZE_TITLE_RE = re.compile(r"[^a-z0-9 ]+")


def normalize_title(title: str) -> str:
    """Deterministic, punctuation/case-insensitive key for matching an
    assignment title across Classroom and Genesis - the two systems name
    the same underlying course completely differently (see
    course_codes_from_name), but confirmed real cases where the same
    assignment's title is identical apart from case/quoting (e.g. "Course
    Syllabus" in both). No fuzzy/edit-distance matching - an exact
    normalized match is the deliberately conservative choice, so a
    mismatch reads as "not tracked consistently between the two systems",
    which is real signal, not noise to explain away."""
    return re.sub(r"\s+", " ", _NORMALIZE_TITLE_RE.sub("", title.lower())).strip()


# Genesis's own term labels. FY/S1/S2 are the confirmed real ones; the rest
# of the closed set is allowed so an unseen label picks the right layout
# rather than silently mis-zipping. An unrecognized value just falls back to
# the teacher-present layout, which is the previous behaviour.
_LIST_TERM_RE = re.compile(r"^(?:FY|S[1-4]|Q[1-4]|MP[1-4]|T[1-4])$")


def extract_genesis_list_blocks(text: str) -> list[ListBlock] | None:
    """List View: fixed 9-line group anchored on the literal "Period"
    line - course/term/teacher/"Room"/roomVal/"Period"/periodVal/
    ["Days"/daysVal]. Anchoring on "Period" (checking "Room" sits exactly
    2 lines above) avoids false positives from the word appearing
    elsewhere on the page.

    A lunch row has no teacher line, which shifts every field up by one -
    confirmed real ("LUNCH/BREAK 2"/"FY"/"Room"/"CAF"/"Period"/"L2"). It
    still satisfies the "Room" guard, so the fixed offsets parsed it
    silently wrong: the course came out as the *previous* block's days
    value ("246"), the term as the course name, and the teacher as the
    term. The two layouts are told apart by which slot holds the term,
    which is a small closed set - no fuzzy matching."""
    lines = text.split("\n")
    blocks: list[ListBlock] = []
    for i, line in enumerate(lines):
        if line != "Period":
            continue
        if i < 2 or lines[i - 2] != "Room":
            continue
        if i < 4:
            continue
        if _LIST_TERM_RE.match(lines[i - 3]):
            course, term, teacher = lines[i - 4], lines[i - 3], None
        elif i >= 5:
            course, term, teacher = lines[i - 5], lines[i - 4], lines[i - 3]
        else:
            continue
        room = lines[i - 1]
        period_val = lines[i + 1] if i + 1 < len(lines) else None
        days = lines[i + 3] if i + 2 < len(lines) and lines[i + 2] == "Days" and i + 3 < len(lines) else None
        if course and period_val:
            blocks.append(ListBlock(period=period_val, course=course, term=term, teacher=teacher, room=room, days=days))
    return blocks or None


# ---- due-date resolution ---------------------------------------------------

_MONTHS = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
}
_WEEKDAYS = {"mon": 0, "tue": 1, "wed": 2, "thu": 3, "fri": 4, "sat": 5, "sun": 6}


def resolve_due_date(due_raw: str | None, captured_at: datetime) -> str | None:
    """Resolves relative/partial due-date text deterministically from the
    capture's own captured_at, never by asking a model - same lesson
    schoolz's own date pipeline learned the hard way (see
    content_extractor.py's _parse_date). Returns an ISO date string or
    None if unrecognized - callers should still show due_raw verbatim
    rather than hiding an unparsed date."""
    if not due_raw:
        return None
    anchor = _local_anchor(captured_at)
    text = re.sub(r"^due\s+", "", due_raw.strip(), flags=re.I)

    if re.match(r"^today", text, re.I) or _TIME_ONLY_RE.match(text):
        return anchor.isoformat()
    if re.match(r"^tomorrow", text, re.I):
        return (anchor + timedelta(days=1)).isoformat()

    m = re.match(r"^(Sun|Mon|Tue|Wed|Thu|Fri|Sat)[a-z]*,?\s*(.*)$", text, re.I)
    if m and not re.match(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)", m.group(2), re.I):
        if m.group(2) and not _TIME_ONLY_RE.match(m.group(2)):
            return None
        target = _WEEKDAYS[m.group(1).lower()[:3]]
        for i in range(1, 8):
            d = anchor + timedelta(days=i)
            if d.weekday() == target:
                return d.isoformat()
    if m:
        text = m.group(2)

    m = _MONTH_DAY_RE.match(text)
    if m:
        month = _MONTHS[m.group(1).lower()]
        day = int(m.group(2))
        # Classroom spells the year out exactly when a bare month/day would
        # be ambiguous - confirmed real on one Classwork page, where a
        # ~4-month-old item reads "Due May 11, 7:30 AM" and one over a year
        # old reads "Due Sep 4, 2025, 11:30 AM" (backpack-capture's
        # docs/DESIGN.md). When it's there it's authoritative and must win:
        # inferring instead silently re-dated genuinely old work into the
        # current school year, which made stale assignments reappear as
        # current ones - and, since late-credit is computed from this date,
        # gave them a live "still worth N%" that was pure fiction.
        explicit_year = _EXPLICIT_YEAR_RE.match(text[m.end() :])
        if explicit_year:
            return date(int(explicit_year.group(1)), month, day).isoformat()
        # A U.S. school year runs roughly Jul-Jun, not Jan-Dec - a due date
        # in Jul-Dec belongs to the school year that started that same
        # calendar year, one in Jan-Jun belongs to the school year that
        # started the *previous* calendar year. So "Jun 10" captured in
        # September isn't 3 months in the past, it's next June (the end of
        # the school year that just started) - and "Sep 3" captured the
        # same September genuinely is a few days in the past, not a whole
        # year off. A day-count threshold can't distinguish these two
        # cases correctly; the school-year boundary can.
        school_year_start = anchor.year if anchor.month >= 7 else anchor.year - 1
        year = school_year_start if month >= 7 else school_year_start + 1
        return date(year, month, day).isoformat()

    return None


_LOCAL_TZ = ZoneInfo("America/New_York")
_TIME_ONLY_RE = re.compile(r"^\d{1,2}:\d{2}\s*(AM|PM)?$", re.I)
_MONTH_DAY_RE = re.compile(r"^(Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\.?\s+(\d{1,2})", re.I)
# The year in "Sep 4, 2025, 11:30 AM", anchored so it only ever matches a year
# sitting immediately after the day - a clock time ("Sep 16, 9:30 AM") must
# never be read as one.
_EXPLICIT_YEAR_RE = re.compile(r"^,?\s*(20\d{2})\b")


def _local_anchor(captured_at: datetime) -> date:
    # Relative words ("Today", "7:30 AM") mean the family's local day - an
    # evening capture is already tomorrow in UTC.
    if captured_at.tzinfo is None:
        return captured_at.date()
    return captured_at.astimezone(_LOCAL_TZ).date()


def resolve_posted_date(posted_raw: str | None, captured_at: datetime) -> str | None:
    """Like resolve_due_date, but a posted date is always in the past: a bare
    "Dec 20" captured in January is last December, and a time-only "10:12 AM"
    (Classroom's format for something posted today) is the capture's own day."""
    if not posted_raw:
        return None
    anchor = _local_anchor(captured_at)
    text = re.sub(r"^(posted|created)\s+", "", posted_raw.strip(), flags=re.I)
    if re.match(r"^today", text, re.I) or _TIME_ONLY_RE.match(text):
        return anchor.isoformat()
    if re.match(r"^yesterday", text, re.I):
        return (anchor - timedelta(days=1)).isoformat()
    m = _MONTH_DAY_RE.match(text)
    if not m:
        return None
    month, day = _MONTHS[m.group(1).lower()[:3]], int(m.group(2))
    year_m = re.search(r"\b(20\d{2})\b", text)
    if year_m:
        return date(int(year_m.group(1)), month, day).isoformat()
    try:
        candidate = date(anchor.year, month, day)
    except ValueError:
        return None
    if candidate > anchor:
        candidate = candidate.replace(year=anchor.year - 1)
    return candidate.isoformat()
