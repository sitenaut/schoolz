"""Extracts structured items from a high school's own "Morning
Announcements" Google Doc - one running document appended to daily,
confirmed real on Cherry Hill East (read aloud over the loudspeaker every
morning by students). The richest source in docs/HS_CLASS_PAGES_DESIGN.md:
club meetings at a specific lunch block, game results, and - uniquely -
same-day logistics ("NO LATE BUSES TODAY") and cancellations that nothing
else in the district publishes.

Split deterministically on the doc's own "Weekday, Month Day, Year" date
headers (Python, not the model - an explicit anchor is right there in the
text) into one block per school day, then one Claude tool-use call per
block. Two rules exist specifically because of this source's shape:

- "TODAY"/"TOMORROW" are resolved against THAT BLOCK's own header date,
  never the date the scan happens to run - the doc is read in full each
  time, so a block from last week still says "TODAY" meaning last week.
- Only blocks newer than School.announcements_last_parsed_date are sent to
  the model at all. The doc grows without bound (this is a running file
  appended to forever, never rotated), so re-sending the whole thing every
  scan would mean an ever-growing bill for zero new information - every
  block older than the watermark has already been extracted and its
  content never changes in place (unlike a Smore newsletter block, which
  can be edited).
"""

import logging
import re
import time
from datetime import date, datetime
from urllib.parse import urlsplit
from zoneinfo import ZoneInfo

import httpx
from anthropic import AsyncAnthropic
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import observability
from models import School, SchoolContentItem
from scheduler.errors import record_parse_issue
from services.class_years import current_grad_years
from services.content_extractor import ANTHROPIC_API_KEY, MODEL

logger = logging.getLogger(__name__)

_JOB_KIND = "hs_announcements.scan"
_ET = ZoneInfo("America/New_York")

_DOC_ID_RE = re.compile(r"/document/d/([a-zA-Z0-9_-]+)")

_MONTHS = [
    "January", "February", "March", "April", "May", "June",
    "July", "August", "September", "October", "November", "December",
]
_HEADER_RE = re.compile(
    r"^(Monday|Tuesday|Wednesday|Thursday|Friday|Saturday|Sunday),\s*"
    r"(" + "|".join(_MONTHS) + r")\s+(\d{1,2})(?:st|nd|rd|th)?,\s*(\d{4})\s*$",
    re.MULTILINE,
)

# 0=senior..3=freshman, matching current_grad_years()' own [senior, junior,
# sophomore, freshman] order - lets a grade word the model transcribes
# ("10th", "sophomores") map straight to an index into that list rather
# than trusting the model to compute an actual graduating year itself.
_GRADE_WORD_TO_INDEX = {
    "freshman": 3, "freshmen": 3, "9th": 3, "9th grade": 3, "9th graders": 3,
    "sophomore": 2, "sophomores": 2, "10th": 2, "10th grade": 2, "10th graders": 2,
    "junior": 1, "juniors": 1, "11th": 1, "11th grade": 1, "11th graders": 1,
    "senior": 0, "seniors": 0, "12th": 0, "12th grade": 0, "12th graders": 0,
}


def doc_export_url(doc_url: str) -> str:
    """Accepts whatever an admin pasted (an /edit link, one with
    ?usp=sharing, or the export URL itself) and returns the canonical
    plain-text export URL - confirmed unauthenticated for a publicly
    shared doc."""
    m = _DOC_ID_RE.search(doc_url)
    doc_id = m.group(1) if m else urlsplit(doc_url).path.strip("/").split("/")[-1]
    return f"https://docs.google.com/document/d/{doc_id}/export?format=txt"


def _month_num(name: str) -> int:
    return _MONTHS.index(name) + 1


def split_day_blocks(doc_text: str) -> list[tuple[date, str]]:
    """Returns [(anchor_date, block_text), ...] - block_text is everything
    between this header and the next (or end of doc)."""
    matches = list(_HEADER_RE.finditer(doc_text))
    blocks = []
    for i, m in enumerate(matches):
        try:
            d = date(int(m.group(4)), _month_num(m.group(2)), int(m.group(3)))
        except ValueError:
            record_parse_issue(_JOB_KIND, "unexpected_format", sample=m.group(0)[:200])
            continue
        end = matches[i + 1].start() if i + 1 < len(matches) else len(doc_text)
        blocks.append((d, doc_text[m.end() : end].strip()))
    return blocks


_EXTRACTION_TOOL = {
    "name": "record_announcements_block",
    "description": "Records structured items from one day's worth of school morning announcements.",
    "input_schema": {
        "type": "object",
        "properties": {
            "items": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "kind": {
                            "type": "string",
                            "enum": ["club_meeting", "game_or_event", "deadline", "logistics", "cancellation", "other"],
                        },
                        "title": {"type": "string", "description": "Short, e.g. 'Ethics Bowl Club Interest Meeting' or 'No Late Buses'."},
                        "description": {"type": "string", "description": "The rest of the detail: what/why, verbatim-ish."},
                        "start_date": {
                            "type": "string",
                            "description": "'YYYY-MM-DD', resolved against THIS BLOCK'S OWN anchor date (given below) - "
                            "'TODAY' means the anchor date exactly, 'TOMORROW' means the day after it, a bare weekday name "
                            "means the next occurrence of that weekday at or after the anchor. Always resolve to an "
                            "absolute date - never leave a relative word in this field. Omit only if genuinely undated.",
                        },
                        "lunch_block": {"type": "string", "enum": ["LB1", "LB2", "both", "after_school", "before_school", "morning"]},
                        "room": {"type": "string"},
                        "audience_grades": {
                            "type": "array",
                            "items": {"type": "string"},
                            "description": "Every grade level explicitly named as the audience, each as its own entry "
                            "(e.g. '10th through 12th graders' -> ['10th graders','11th graders','12th graders']; "
                            "'ALL FRESHMEN' -> ['freshmen']). Omit entirely if the item is for the whole school/no "
                            "audience is named - never guess one.",
                        },
                    },
                    "required": ["kind", "title"],
                },
            },
        },
        "required": ["items"],
    },
}

_SYSTEM_PROMPT_TEMPLATE = """You extract structured items from one day's school morning announcements, read aloud \
to students over the loudspeaker. This block is anchored to {anchor_date} ({anchor_weekday}) - resolve every date \
relative to that exact anchor, per the start_date field's own instructions. Extract EVERY distinct \
announcement as its own item - club/interest meetings (with room and lunch block, LB1/LB2/both/after \
school), games and their results, deadlines, and same-day logistics like bus/schedule changes or \
cancellations. A rescheduled or cancelled meeting is its own 'cancellation' item, separate from the \
original announcement of it. Skip pure ceremony/tribute text with no actionable or dated content \
(e.g. a moment-of-silence announcement) and skip vague school-spirit filler with no meeting/date/room. \
Never guess an audience - only set audience_grades when the text explicitly names a grade level or \
class descriptor (freshmen/sophomores/juniors/seniors, or 'Nth grade(rs)')."""


def _grades_to_grad_years(audience_grades: list[str] | None) -> list[int] | None:
    if not audience_grades:
        return None
    years = current_grad_years()
    indices = {_GRADE_WORD_TO_INDEX[g.lower()] for g in audience_grades if g.lower() in _GRADE_WORD_TO_INDEX}
    return sorted({years[i] for i in indices}) or None


def _stable_uid(title: str, start_date: date | None) -> str:
    import hashlib

    digest = hashlib.sha1(f"{title.strip().lower()}|{start_date.isoformat() if start_date else ''}".encode("utf-8")).hexdigest()[:20]
    return f"announcements:{digest}"


async def scan_announcements(db: AsyncSession, school: School) -> str:
    if not ANTHROPIC_API_KEY:
        return "skipped - ANTHROPIC_API_KEY not configured"
    if not school.announcements_doc_url:
        return "no announcements_doc_url configured"

    async with httpx.AsyncClient(timeout=20.0, follow_redirects=True) as client:
        try:
            resp = await client.get(doc_export_url(school.announcements_doc_url), headers={"User-Agent": "schoolz-hs-announcements/1.0"})
            resp.raise_for_status()
        except httpx.HTTPError as exc:
            logger.warning("hs_announcements_fetch_failed", extra={"school_id": school.id, "error": str(exc)})
            return f"WARNING[fetch_failed]: could not fetch announcements doc: {exc}"
        doc_text = resp.text

    blocks = split_day_blocks(doc_text)
    if not blocks:
        return "WARNING[no_day_blocks]: no 'Weekday, Month Day, Year' headers found in the doc"

    watermark = None
    if school.announcements_last_parsed_date:
        try:
            watermark = date.fromisoformat(school.announcements_last_parsed_date)
        except ValueError:
            pass
    new_blocks = [(d, text) for d, text in blocks if watermark is None or d > watermark]
    if not new_blocks:
        return f"no new day blocks since {watermark.isoformat()}"

    client_ai = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    created = updated = 0
    max_date_seen = watermark

    for anchor_date, block_text in new_blocks:
        bullets = [line.strip().lstrip("*").strip() for line in block_text.splitlines() if line.strip().startswith("*")]
        max_date_seen = anchor_date if max_date_seen is None or anchor_date > max_date_seen else max_date_seen
        if not bullets:
            continue

        system_prompt = _SYSTEM_PROMPT_TEMPLATE.format(anchor_date=anchor_date.isoformat(), anchor_weekday=anchor_date.strftime("%A"))
        _llm_started = time.perf_counter()
        response = await client_ai.messages.create(
            model=MODEL,
            max_tokens=4096,
            temperature=0,
            system=system_prompt,
            tools=[_EXTRACTION_TOOL],
            tool_choice={"type": "tool", "name": "record_announcements_block"},
            messages=[{"role": "user", "content": "\n".join(bullets)}],
        )
        observability.record_llm_call("hs_announcements_extract", MODEL, response, time.perf_counter() - _llm_started)
        tool_use = next((b for b in response.content if b.type == "tool_use"), None)
        if not tool_use:
            continue
        if response.stop_reason == "max_tokens":
            record_parse_issue(_JOB_KIND, "llm_max_tokens", school_id=school.id, sample=anchor_date.isoformat())

        for item in tool_use.input.get("items", []):
            # "required" in a tool schema is a hint the model usually
            # follows, not an API-enforced guarantee (confirmed real in
            # services/hs_activities_site.py - a missing title there
            # crashed the whole run). Skip just this one item instead.
            title = item.get("title")
            if not title:
                record_parse_issue(_JOB_KIND, "unexpected_format", school_id=school.id, sample=str(item)[:200])
                continue

            start_date = None
            if item.get("start_date"):
                try:
                    start_date = datetime.fromisoformat(item["start_date"]).replace(tzinfo=_ET)
                except ValueError:
                    record_parse_issue(_JOB_KIND, "unexpected_format", school_id=school.id, sample=item["start_date"][:200])
            uid = _stable_uid(title, start_date.date() if start_date else None)

            row = (
                await db.execute(
                    select(SchoolContentItem).where(
                        SchoolContentItem.school_id == school.id,
                        SchoolContentItem.source == "hs_announcements",
                        SchoolContentItem.external_uid == uid,
                    )
                )
            ).scalar_one_or_none()
            if row is None:
                row = SchoolContentItem(scope="school", school_id=school.id, source="hs_announcements", external_uid=uid)
                db.add(row)
                created += 1
            else:
                updated += 1

            kind = item.get("kind", "other")
            detail = " · ".join(x for x in (item.get("room"), item.get("lunch_block")) if x)
            description = " — ".join(x for x in (item.get("description"), detail) if x) or None

            row.category = "reminder" if kind in ("cancellation", "logistics") else ("deadline" if kind == "deadline" else "event")
            row.title = title[:300]
            row.description = description
            row.start_date = start_date
            row.is_all_day = start_date is None
            row.applies_to_grad_years = _grades_to_grad_years(item.get("audience_grades"))

    if max_date_seen:
        school.announcements_last_parsed_date = max_date_seen.isoformat()
    await db.flush()

    return f"announcements: {len(new_blocks)} day block(s) processed, {created} item(s) created, {updated} updated"
