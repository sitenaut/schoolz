"""A district's school-year calendar published as a PDF, for a district with
no ICS feed (Evesham Township: a ParentSquare Smart Sites page that links one
"2026-27 District Calendar" PDF).

The page is what's tracked, not the file: the PDF's URL changes every year
(and when the board revises it), so each run re-finds the link. The PDF is a
one-page list of dated entries ("26-27  Thu-Fri - Thanksgiving Recess
(Schools Closed)"), read with Claude's native PDF support like the lunch menus.
Entries become district-scoped, all-day SchoolContentItems.

Titles are composed in code from a model-chosen *kind*, never copied from the
PDF, because day status is read off the title (services/school_status.py) and
a printed "Student Two-Hour Delayed Opening/Teacher In-Service" contains
"in-service", which classify_day would read as a closed day. The printed text
is kept verbatim in the description."""

import base64
import hashlib
import logging
import re
import time
from datetime import date, datetime, time as dtime, timedelta
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from anthropic import AsyncAnthropic

import observability
from services.content_extractor import ANTHROPIC_API_KEY, MODEL
from services.school_status import CLOSED_RE

logger = logging.getLogger(__name__)

TZ = ZoneInfo("America/New_York")
SOURCE = "district_pdf"
UID_PREFIX = "dcpdf"
_HEADERS = {"User-Agent": "Mozilla/5.0 (schoolz calendar sync)"}
_PDF_URL_RE = re.compile(r"""https?://[^\s"'<>\\]+?\.pdf(?:\?[^\s"'<>\\]*)?""", re.I)

_KINDS = ["closed", "early_dismissal", "delayed_opening", "other"]
_CALENDAR_TOOL = {
    "name": "record_calendar",
    "description": "Record every dated entry of the school calendar.",
    "input_schema": {
        "type": "object",
        "properties": {
            "events": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "start_date": {"type": "string", "description": "ISO date of the first day, with the correct year for that month."},
                        "end_date": {"type": "string", "description": "ISO date of the LAST day (inclusive). Same as start_date for a single day."},
                        "kind": {
                            "type": "string",
                            "enum": _KINDS,
                            "description": "closed = no school for students (even if teachers work); early_dismissal = students dismissed early; "
                            "delayed_opening = students arrive late; other = anything else (first/last day, school reopens, holidays the PDF does not say are closed).",
                        },
                        "subject": {"type": "string", "description": "Short name of the reason, e.g. 'Yom Kippur', 'Parent/Teacher Conferences', 'Winter Recess', 'Primary Election Day'. Leave out the kind itself ('Schools Closed', 'Early Dismissal', 'Delayed Opening', 'Teacher In-Service') unless it is the only thing printed; empty is fine for a plain early dismissal."},
                        "printed": {"type": "string", "description": "The entry exactly as printed, including any parenthetical."},
                    },
                    "required": ["start_date", "end_date", "kind", "subject", "printed"],
                },
            },
            "academic_year": {"type": "string", "description": "e.g. '2026-27'"},
        },
        "required": ["events"],
    },
}


def find_pdf_link(html: str, page_url: str) -> str | None:
    """The calendar PDF on a page. Smart Sites' document-viewer pages are
    client-rendered but carry the file URL JSON-escaped ("https:\\/\\/files...")
    in inline script, so un-escape before looking. Several PDFs: prefer one
    whose name says calendar."""
    text = html.replace("\\/", "/")
    found: list[str] = []
    for m in _PDF_URL_RE.finditer(text):
        if m.group(0) not in found:
            found.append(m.group(0))
    for m in re.finditer(r"""href=["']([^"']+\.pdf[^"']*)["']""", text, re.I):
        url = urljoin(page_url, m.group(1))
        if url not in found:
            found.append(url)
    if not found:
        return None
    return next((u for u in found if "calendar" in u.lower()), found[0])


async def fetch_pdf(page_url: str) -> tuple[str, bytes] | None:
    """(pdf_url, bytes) for a tracked page, or None if no PDF link is on it.
    The URL may itself be the PDF."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
        resp = await client.get(page_url)
        resp.raise_for_status()
        if resp.content[:5] == b"%PDF-":
            return str(resp.url), resp.content
        pdf_url = find_pdf_link(resp.text, str(resp.url))
        if not pdf_url:
            return None
        pdf = await client.get(pdf_url)
        pdf.raise_for_status()
        return pdf_url, pdf.content


_PARSER_VERSION = b"1"  # bump when title composition or the prompt changes, so stored rows are rebuilt


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data + _PARSER_VERSION).hexdigest()[:10]


async def extract_events(pdf_bytes: bytes) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        return []
    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    started = time.perf_counter()
    response = await client.messages.create(
        model=MODEL,
        max_tokens=8192,
        temperature=0,
        tools=[_CALENDAR_TOOL],
        tool_choice={"type": "tool", "name": "record_calendar"},
        messages=[
            {
                "role": "user",
                "content": [
                    {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode("ascii")}},
                    {
                        "type": "text",
                        "text": "This is a school district's school-year calendar. Record every dated entry in the event list "
                        "(closures, recesses, early dismissals, delayed openings, first and last student day, conferences, holidays). "
                        "A range like '26-27 Thu-Fri' is one entry from the 26th to the 27th; a month-header above the list gives the month, "
                        "and the school year in the title gives the year (fall months are the first year, January-June the second). "
                        "Do NOT record the mini month grids, the days-in-session table or the key. Do not record the emergency/snow make-up "
                        "day list. Only mark an entry 'closed' if the printed text says schools are closed.",
                    },
                ],
            }
        ],
    )
    observability.record_llm_call("district_calendar_pdf", MODEL, response, time.perf_counter() - started)
    tool_use = next((b for b in response.content if b.type == "tool_use"), None)
    if not tool_use:
        return []
    return list(tool_use.input.get("events", []))


def _defang(subject: str) -> str:
    """Keep only the reason, without any word classify_day reads as a closure
    or restates the kind, so an early-dismissal title can't turn the day into
    'closed' and never says "Early Dismissal - Student Early Dismissal"."""
    s = re.sub(r"\bconferences?\b", "Meetings", subject, flags=re.I)
    s = re.sub(r"[/\s]*\b(teachers?\s+)?in-?service\b", "", s, flags=re.I)
    s = re.sub(r"\b(student\s+)?early\s+dismissal\b", "", s, flags=re.I)
    s = re.sub(r"\bstudents?\b", "", s, flags=re.I)
    s = CLOSED_RE.sub("", s)
    if s.count("(") != s.count(")"):
        s = s.replace("(", " ").replace(")", " ")
    s = re.sub(r"\(\s*\)", "", s)
    s = " ".join(s.split()).strip(" -/,")
    return s[1:-1].strip() if s.startswith("(") and s.endswith(")") and s.count("(") == 1 else s


def compose_title(kind: str, subject: str) -> str:
    subject = " ".join(subject.split())
    if kind == "closed":
        return f"Schools Closed - {subject}" if subject and not re.search(r"\bclosed\b", subject, re.I) else (subject or "Schools Closed")
    if kind == "early_dismissal":
        safe = _defang(subject)
        return f"Early Dismissal - {safe}" if safe and safe.lower() != "early dismissal" else "Early Dismissal"
    if kind == "delayed_opening":
        return "Two-Hour Delayed Opening"
    return subject or "School calendar"


def _iso(value: object) -> date | None:
    try:
        return date.fromisoformat(str(value)[:10])
    except ValueError:
        return None


def build_items(events: list[dict], pdf_url: str, digest: str) -> tuple[dict[str, dict], int]:
    """({external_uid: SchoolContentItem fields}, skipped) from the model's
    events. An entry with an unreadable or implausible date is skipped, not
    guessed."""
    wanted: dict[str, dict] = {}
    skipped = 0
    for ev in events:
        start, end = _iso(ev.get("start_date")), _iso(ev.get("end_date")) or _iso(ev.get("start_date"))
        if not start or not end or end < start or not (2020 <= start.year <= 2100) or (end - start).days > 60:
            skipped += 1
            continue
        kind = ev.get("kind") if ev.get("kind") in _KINDS else "other"
        title = compose_title(kind, str(ev.get("subject") or ""))
        uid = f"{UID_PREFIX}:{digest}:{start.isoformat()}:{kind}:{re.sub(r'[^a-z0-9]+', '-', title.lower()).strip('-')[:60]}"
        fields = {
            "title": title[:300],
            "description": (str(ev.get("printed") or "").strip() or None),
            "start_date": datetime.combine(start, dtime.min, TZ),
            "link_url": pdf_url,
        }
        if end > start:
            fields["end_date"] = datetime.combine(end + timedelta(days=1), dtime.min, TZ)
        wanted[uid] = fields
    return wanted, skipped
