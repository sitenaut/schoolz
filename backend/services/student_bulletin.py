"""A school's weekly student bulletin kept as a Google Doc that its office
rewrites in place (Marlton Middle: spirit days, delayed openings, club
sign-ups with Classroom codes, fees, late-bus and early-dismissal rules,
house-office contacts, fall-sports schedules). Unlike hs_announcements it
is not append-only, so the whole doc is re-read on change: a content hash
on School skips the model when nothing moved, and rows whose line vanished
are deleted (same as school_events_doc).

Three parts, split by what a regex can do reliably:
- sports schedules ("* 10/5: Delran at MMS 3:45pm" under a team heading) and
  house-office contacts ("Blue House ext. 8509" + email) are deterministic;
- everything else - year-less dates, club blurbs, fees, standing rules - is
  one Claude tool-use call given today's date to resolve years against.
"""

import hashlib
import logging
import re
import time
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import School, SchoolContentItem, StaffMember
from scheduler.errors import record_parse_issue
from services.content_extractor import ANTHROPIC_API_KEY, MODEL
from services.hs_announcements import doc_export_url
from services.school_status import is_status_title, status_kind
from services.tool_output import object_list, recover_spilled_input

logger = logging.getLogger(__name__)

_JOB_KIND = "student_bulletin.scan"
SOURCE = "bulletin"
_ET = ZoneInfo("America/New_York")

_SPORTS_HEADING_RE = re.compile(r"^\s*[A-Z ]*SPORTS?\s+SCHEDULES?\s*:?\s*$", re.I | re.M)
_TEAM_RE = re.compile(r"^\s*([A-Za-z][A-Za-z .&/'-]{2,60}?)\s*:(.*)$")
_GAME_RE = re.compile(r"^\s*[*•-]\s*(\d{1,2})/(\d{1,2})(?::|\s)\s*(.+?)\s*$")
_TIME_RE = re.compile(r"\b(\d{1,2})(?::(\d{2}))?\s*([ap])\.?m\.?\b", re.I)
_HOUSE_RE = re.compile(r"([A-Z][a-z]+ House)\s+ext\.?\s*(\d+)\s+([\w.+-]+@[\w-]+(?:\.[\w-]+)+)", re.I)
_SCHOOL_PHONE_RE = re.compile(r"^\s*[A-Z]{2,6}:\s*(\(\d{3}\)\s*\d{3}-\d{4})\s*$", re.M)


def split_sports(text: str) -> tuple[str, str]:
    """(everything before the sports section, the sports section)."""
    m = _SPORTS_HEADING_RE.search(text)
    return (text[: m.start()], text[m.end() :]) if m else (text, "")


def resolve_year(month: int, day: int, today: date) -> date | None:
    """A bulletin prints no year. The date is the occurrence closest to
    today, within ~60 days back and the rest of a year forward."""
    for year in (today.year - 1, today.year, today.year + 1):
        try:
            d = date(year, month, day)
        except ValueError:
            return None
        if today - timedelta(days=60) <= d < today - timedelta(days=60) + timedelta(days=365):
            return d
    return None


def _to_time(m: re.Match[str]) -> tuple[int, int]:
    hour = int(m.group(1)) % 12 + (12 if m.group(3).lower() == "p" else 0)
    return hour, int(m.group(2) or 0)


def parse_sports(section: str, today: date, tag: str = "MMS") -> list[dict]:
    """Team headings end in ':' and games are '* M/D: ...' bullets. A heading's
    own remainder ('Cross Country:  All start 3:45pm') is the default time
    for its games that name none."""
    games: list[dict] = []
    team, default_time = None, None
    for line in section.splitlines():
        g = _GAME_RE.match(line)
        if g and team:
            d = resolve_year(int(g.group(1)), int(g.group(2)), today)
            if not d:
                continue
            detail = g.group(3)
            tm = _TIME_RE.search(detail) or default_time
            what = _TIME_RE.sub("", detail).strip(" -,") if _TIME_RE.search(detail) else detail.strip()
            team_label = re.sub(rf"^{tag}\s+", "", team)
            title = f"{team_label}: {what}"
            if tm is not None:
                h, mi = _to_time(tm)
                start, all_day = datetime(d.year, d.month, d.day, h, mi, tzinfo=_ET), False
            else:
                start, all_day = datetime(d.year, d.month, d.day, tzinfo=_ET), True
            games.append({"title": title[:300], "start_date": start, "is_all_day": all_day, "line": line.strip()[:300]})
            continue
        t = _TEAM_RE.match(line)
        if t and not _GAME_RE.match(line):
            team = t.group(1).strip()
            default_time = _TIME_RE.search(t.group(2))
    return games


def parse_houses(text: str) -> list[dict]:
    phone = _SCHOOL_PHONE_RE.search(text)
    main = phone.group(1) if phone else None
    out = []
    for name, ext, email in _HOUSE_RE.findall(text):
        out.append(
            {
                "constituent_id": f"bulletin:{name.lower().replace(' ', '-')}",
                "full_name": f"{name.title()} office",
                "title": f"{name.title()} office (absences and early dismissal)",
                "email": email.lower(),
                "phone": f"{main} ext. {ext}" if main else f"ext. {ext}",
            }
        )
    return out


_EXTRACTION_TOOL = {
    "name": "record_bulletin_items",
    "description": "Records the structured items from a school's student bulletin.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "category": {
                            "type": "string",
                            "enum": ["event", "deadline", "org_club", "procedure", "reminder"],
                            "description": "event = dated happening (spirit day, pizza day, bingo, delayed opening); "
                            "org_club = a club/activity to join; procedure = standing how-it-works rule "
                            "(late buses, early dismissal, sign-out); reminder = other standing notice "
                            "(earbuds, peer tutoring, fees, lunch passes); deadline = a dated thing to do by.",
                        },
                        "title": {"type": "string", "description": "Short, e.g. 'Spirit Day: Pink Out' or 'Pickleball Club'."},
                        "description": {
                            "type": "string",
                            "description": "Everything a parent needs, kept concrete: room, weekday, sign-up Google Classroom "
                            "code (verbatim), fee, requirement, other dates. Do not pad.",
                        },
                        "start_date": {
                            "type": "string",
                            "description": "'YYYY-MM-DD', or 'YYYY-MM-DDTHH:MM' if a time is stated. For a club, its first "
                            "meeting. Bare month/day dates carry no year - resolve them against today's date given "
                            "in the system prompt. Omit for standing items with no date.",
                        },
                        "end_date": {"type": "string", "description": "Only for a stated range."},
                        "link_url": {"type": "string", "description": "Only a URL literally present in the text."},
                    },
                    "required": ["category", "title"],
                },
            },
        },
        "required": ["items"],
    },
}

_SYSTEM_PROMPT = """You turn a middle school's weekly student bulletin into structured items. Today is {today} \
({weekday}). Dates in the bulletin have no year: pick the nearest occurrence of that month/day at or after the \
start of the current school year, never a year already long past. Extract EVERY distinct item: each spirit day \
(title carries the theme, e.g. 'Spirit Day: Pink Out'), delayed openings (keep the time in the title), grade-level \
events (say if pick-up only), every club with its meeting day, room, first meeting, Google Classroom code and \
requirements, each dated food day (pizza day - one item per date, with price), the registration and payment info (a separate \
reminder stating each fee, e.g. travel sports and clubs, and how to sign up), and the standing rules \
(late-bus holding area and hours, early dismissal and absence procedure including the ID requirement, wired \
earbuds, peer tutoring location, lunch-in-the-library sign-up). One item per club or rule; do not merge them. \
Each item must stand alone - a reader will see it without the rest of the bulletin. Do NOT extract sports game \
schedules (handled separately) or contact phone/email lists. Never invent a date, room, code, or price."""


def _fmt(value: str | None) -> tuple[datetime | None, bool]:
    if not value:
        return None, True
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        record_parse_issue(_JOB_KIND, "unexpected_format", sample=value[:200])
        return None, True
    all_day = "T" not in value and " " not in value.strip()
    return parsed.replace(tzinfo=_ET) if parsed.tzinfo is None else parsed, all_day


def _uid(category: str, title: str, start: datetime | None) -> str:
    key = f"{category}|{title.strip().lower()}|{start.date().isoformat() if start else ''}"
    return f"{SOURCE}:{hashlib.sha1(key.encode('utf-8')).hexdigest()[:20]}"


def build_items(raw_items: list[dict], today: date, doc_url: str | None = None) -> list[dict]:
    """Pure: model output -> row values. A date more than 60 days stale is
    the model reading a year-less date against the wrong year, so it rolls a
    year forward (same as content_extractor._correct_stale_year)."""
    out, seen = [], set()
    for it in raw_items:
        title = re.sub(r"\s+", " ", (it.get("title") or "").replace("*", "")).strip()
        category = it.get("category") or "reminder"
        if not title:
            continue
        start, all_day = _fmt(it.get("start_date"))
        end, _ = _fmt(it.get("end_date"))
        if start and start.date() < today - timedelta(days=60):
            start = start.replace(year=start.year + 1)
            end = end.replace(year=end.year + 1) if end else None
        uid = _uid(category, title, start)
        if uid in seen:
            continue
        seen.add(uid)
        out.append(
            {
                "uid": uid,
                "category": category,
                "title": title[:300],
                "description": (it.get("description") or "").strip() or None,
                "start_date": start,
                "end_date": end,
                "is_all_day": all_day,
                "link_url": (it.get("link_url") or doc_url or None),
            }
        )
    return out


async def _district_status_days(db: AsyncSession, school: School) -> set[tuple[str, date]]:
    if not school.district_id:
        return set()
    rows = (
        await db.execute(
            select(SchoolContentItem.title, SchoolContentItem.start_date).where(
                SchoolContentItem.district_id == school.district_id,
                SchoolContentItem.is_current.is_(True),
                SchoolContentItem.start_date.is_not(None),
            )
        )
    ).all()
    return {(k, d.astimezone(_ET).date()) for t, d in rows if (k := status_kind(t))}


async def scan_bulletin(db: AsyncSession, school: School) -> str:
    if not school.bulletin_doc_url:
        return "no bulletin_doc_url configured"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(doc_export_url(school.bulletin_doc_url), headers={"User-Agent": "schoolz-student-bulletin/1.0"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("student_bulletin_fetch_failed", extra={"school_id": school.id, "error": str(exc)})
            return f"WARNING[fetch_failed]: could not fetch bulletin doc: {exc}"
        resp.encoding = "utf-8"
        text = resp.text

    today = datetime.now(_ET).date()
    # The date is in the hash: a year-less doc resolves differently across the school-year boundary.
    digest = hashlib.sha256(f"{text}|{today.year}".encode("utf-8")).hexdigest()
    if digest == school.bulletin_content_hash:
        return "bulletin unchanged since last scan"
    if not ANTHROPIC_API_KEY:
        return "skipped - ANTHROPIC_API_KEY not configured"

    body, sports_section = split_sports(text)
    games = parse_sports(sports_section, today)
    houses = parse_houses(text)

    client_ai = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    started = time.perf_counter()
    response = await client_ai.messages.create(
        model=MODEL,
        max_tokens=8192,
        temperature=0,
        system=_SYSTEM_PROMPT.format(today=today.isoformat(), weekday=today.strftime("%A")),
        tools=[_EXTRACTION_TOOL],
        tool_choice={"type": "tool", "name": "record_bulletin_items"},
        messages=[{"role": "user", "content": body}],
    )
    observability.record_llm_call("student_bulletin_extract", MODEL, response, time.perf_counter() - started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if response.stop_reason == "max_tokens":
        record_parse_issue(_JOB_KIND, "llm_max_tokens", school_id=school.id)
    raw, dropped = object_list(recover_spilled_input(tool_use.input).get("items")) if tool_use else ([], [])
    if dropped:
        record_parse_issue(_JOB_KIND, "unexpected_format", school_id=school.id, sample=str(dropped)[:200])

    items = build_items(raw, today, school.bulletin_doc_url)
    district_days = await _district_status_days(db, school)
    items = [
        i
        for i in items
        if not (i["start_date"] and not _TIME_RE.search(i["title"]) and is_status_title(i["title"]) and (status_kind(i["title"]), i["start_date"].astimezone(_ET).date()) in district_days)
    ]
    for g in games:
        items.append(
            {
                "uid": _uid("event", g["title"], g["start_date"]),
                "category": "event",
                "title": g["title"],
                "description": None,
                "start_date": g["start_date"],
                "end_date": None,
                "is_all_day": g["is_all_day"],
                "link_url": school.bulletin_doc_url,
                "excerpt": g["line"],
            }
        )

    if not items:
        # Never prune on an empty parse - a restructured doc shouldn't wipe what's already shown.
        return "WARNING[no_items]: nothing extracted from the bulletin"

    existing = {
        r.external_uid: r
        for r in (
            await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id, SchoolContentItem.source == SOURCE))
        ).scalars()
    }
    seen: set[str] = set()
    created = updated = 0
    for i in items:
        if i["uid"] in seen:
            continue
        seen.add(i["uid"])
        row = existing.get(i["uid"])
        if row is None:
            row = SchoolContentItem(scope="school", school_id=school.id, source=SOURCE, external_uid=i["uid"])
            db.add(row)
            created += 1
        else:
            updated += 1
        row.category = i["category"]
        row.title = i["title"]
        row.description = i["description"]
        row.start_date = i["start_date"]
        row.end_date = i["end_date"]
        row.is_all_day = i["is_all_day"]
        row.link_url = (i["link_url"] or "")[:1000] or None
        row.source_excerpt = i.get("excerpt")
        row.is_current = True
    removed = 0
    for uid, row in existing.items():
        if uid not in seen:
            await db.delete(row)
            removed += 1

    staff_existing = {
        s.source_constituent_id: s
        for s in (await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))).scalars()
    }
    for h in houses:
        s = staff_existing.get(h["constituent_id"])
        if s is None:
            s = StaffMember(school_id=school.id, source_constituent_id=h["constituent_id"])
            db.add(s)
        s.full_name, s.title, s.email, s.phone = h["full_name"], h["title"], h["email"], h["phone"]

    school.bulletin_content_hash = digest
    await db.flush()
    return (
        f"bulletin: {len(seen)} item(s) ({len(games)} games) - {created} created, {updated} updated, {removed} removed; "
        f"{len(houses)} house office contact(s)"
    )
