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
from datetime import date, datetime, timedelta
from datetime import time as dtime
from urllib.parse import urljoin
from zoneinfo import ZoneInfo

import httpx
from anthropic import AsyncAnthropic

import observability
import scraper_client
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


_BASE_HREF_RE = re.compile(r"""<base\s[^>]*href=["']([^"']+)["']""", re.I)
_RESOURCE_ANCHOR_RE = re.compile(
    r"""<a\s(?=[^>]*data-file-name=["'](?P<name>[^"']+\.pdf)["'])(?=[^>]*href=["'](?P<href>[^"']*/fs/resource-manager/view/[^"']+)["'])[^>]*>""",
    re.I,
)
_DRIVE_ANCHOR_RE = re.compile(r"""<a\s[^>]*href=["'][^"']*drive\.google\.com/file/d/([\w-]{20,})/[^"']*["'][^>]*>""", re.I)


def _drive_calendar_link(text: str) -> str | None:
    """Clementon posts "2026-27 Calendar (Approved 2.12.26) - English / Spanish"
    as Drive links, no .pdf anywhere. The first Drive file whose preceding
    text says calendar is the English one."""
    for m in _DRIVE_ANCHOR_RE.finditer(text):
        before = text[max(0, m.start() - 300) : m.start()]
        # Only the text sitting right against the link: back to the previous
        # link or block, so a nav bar's "Calendar" can't label a later file.
        boundary = max((mm.end() for mm in re.finditer(r"</a>|</?(?:p|div|li|br|td|tr|h\d)\b[^>]*>", before, re.I)), default=0)
        lead = re.sub(r"<[^>]+>|\s+", " ", before[boundary:]).strip()
        if "calendar" in lead.lower():
            return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    return None


def find_pdf_link(html: str, page_url: str) -> str | None:
    """The calendar PDF on a page. Smart Sites' document-viewer pages are
    client-rendered but carry the file URL JSON-escaped ("https:\\/\\/files...")
    in inline script, so un-escape before looking. Several PDFs: prefer one
    whose name says calendar, then a Drive file labelled calendar; only then
    the first PDF. Relative links resolve against <base href> when present
    (Clementon's pages sit in subfolders but link from the site root)."""
    text = html.replace("\\/", "/")
    base = _BASE_HREF_RE.search(text)
    base_url = urljoin(page_url, base.group(1)) if base else page_url
    # Finalsite resource-manager links carry the filename only in
    # data-file-name; the href is a /fs/resource-manager/view/<uuid> redirect.
    # Pennsauken's page lists its year calendar this way above a school's
    # direct-linked "CarsonCalendarforSept2026.pdf", so these come first.
    for m in _RESOURCE_ANCHOR_RE.finditer(text):
        if "calendar" in m.group("name").lower():
            return urljoin(base_url, m.group("href"))
    found: list[str] = []
    for m in _PDF_URL_RE.finditer(text):
        if m.group(0) not in found:
            found.append(m.group(0))
    for m in re.finditer(r"""href=["']([^"']+\.pdf[^"']*)["']""", text, re.I):
        url = urljoin(base_url, m.group(1))
        if url not in found:
            found.append(url)
    named_all = [u for u in found if "calendar" in u.lower()]
    # St. Joan of Arc's homepage links a monthly "2026-10-Calendar.pdf" above
    # the year's "school-calendar-2026-2027-....pdf": prefer the school-year name.
    named = next((u for u in named_all if re.search(r"20\d\d[-_.]20\d\d|\b\d\d-\d\d\b", u.rsplit("/", 1)[-1])), None) or (named_all[0] if named_all else None)
    if named:
        return named
    return _drive_calendar_link(text) or (found[0] if found else None)


async def fetch_pdf(page_url: str) -> tuple[str, bytes] | None:
    """(pdf_url, bytes) for a tracked page, or None if no PDF link is on it.
    The URL may itself be the PDF."""
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=_HEADERS) as client:
        resp = await client.get(page_url)
    if resp.status_code == 403:
        # A site that refuses Fly's addresses (Wood-Ridge: 200 from a home
        # network, a bot challenge to a plain fetch through a scraper) is
        # rendered in a scraper's browser instead, and only a copy carrying
        # the calendar link counts.
        final_url = page_url
        html = await scraper_client.fetch_html_from_any(page_url, accept=lambda h: find_pdf_link(h, page_url) is not None)
    else:
        resp.raise_for_status()
        if resp.content[:5] == b"%PDF-":
            return str(resp.url), resp.content
        final_url, html = str(resp.url), resp.text
    pdf_url = find_pdf_link(html, final_url)
    if not pdf_url:
        return None
    _, pdf = await scraper_client.get_bytes(pdf_url, headers=_HEADERS)
    return pdf_url, pdf


_PARSER_VERSION = b"3"  # bump when title composition or the prompt changes, so stored rows are rebuilt


def content_hash(data: bytes) -> str:
    return hashlib.sha256(data + _PARSER_VERSION).hexdigest()[:10]


_MONTH_NAMES = ("JANUARY", "FEBRUARY", "MARCH", "APRIL", "MAY", "JUNE", "JULY", "AUGUST", "SEPTEMBER", "OCTOBER", "NOVEMBER", "DECEMBER")
_MONTH_NUM = {name: i + 1 for i, name in enumerate(_MONTH_NAMES)}
_ENTRY_START_RE = re.compile(r"^\d{1,2}(?:\s*[-\u2013]\s*\d{1,2})?$")


def layout_text_by_month(pdf_bytes: bytes) -> str | None:
    """A year-at-a-glance calendar laid out as two columns of six mini-month
    grids (Gateway Regional: July-December down the left, January-June down
    the right), each month's event list printed beside its grid. Read as a
    whole the page interleaves the two columns, and the model put right-column
    entries under the wrong month (Spring Break in February, Memorial Day
    closing April 28 to May 31). Here each entry is assigned to its month by
    position: the list sits in its month header's row, in the text lane next
    to that column's grid. None when the page is not that layout, so any other
    PDF keeps the plain read."""
    try:
        import io

        import pdfplumber

        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            if len(pdf.pages) != 1:
                return None
            page = pdf.pages[0]
            words = page.extract_words()
            width = float(page.width)
    except Exception:  # noqa: BLE001 - not a PDF, or one pdfplumber cannot read
        return None

    headers = []  # (top, x0, month, year)
    for w in words:
        month = _MONTH_NUM.get(w["text"])
        if not month:
            continue
        year = next((x["text"] for x in words if abs(x["top"] - w["top"]) < 3 and 0 < x["x0"] - w["x1"] < 12 and re.fullmatch(r"20\d\d", x["text"])), None)
        if year:
            headers.append((w["top"], w["x0"], month, int(year)))
    left = sorted((h for h in headers if h[1] < width / 2), key=lambda h: h[0])
    right = sorted((h for h in headers if h[1] >= width / 2), key=lambda h: h[0])
    if len(left) != 6 or len(right) != 6 or any(abs(a[0] - b[0]) > 4 for a, b in zip(left, right, strict=True)):
        return None

    # Text lanes: the left column's list begins just past its grid, the right
    # column's after the page middle; the right grid starts ~35pt left of its header.
    mid = width * 0.49
    lanes = {"left": (left[0][1] + 85, mid), "right": (mid, right[0][1] - 35)}
    row_tops = [h[0] for h in left]
    pitch = (row_tops[-1] - row_tops[0]) / 5  # a month row's height; the notes under the last row are not its entries
    blocks: dict[tuple[str, int], list[list[str]]] = {("left", i): [] for i in range(6)} | {("right", i): [] for i in range(6)}

    last_top: dict[tuple[str, int], float] = {}
    lines: dict[tuple[str, int], list[dict]] = {}
    for w in words:
        for side, (x_from, x_to) in lanes.items():
            if x_from <= w["x0"] < x_to:
                lines.setdefault((side, round(w["top"])), []).append(w)
    for (side, top), ws in sorted(lines.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        ws.sort(key=lambda w: w["x0"])
        text = " ".join(w["text"] for w in ws)
        if re.match(r"^(student|teacher)\b", text, re.I):
            continue  # the days-in-session table
        row = max((i for i, t in enumerate(row_tops) if top >= t - 8), default=None)
        if row is None or top >= row_tops[row] + pitch - 8:
            continue
        entries = blocks[(side, row)]
        if _ENTRY_START_RE.match(ws[0]["text"]):
            entries.append([text])
            last_top[(side, row)] = top
        elif entries and top - last_top[(side, row)] <= 12:
            entries[-1].append(text)  # a wrapped second line of the entry above
            last_top[(side, row)] = top

    out = []
    for side, column in (("left", left), ("right", right)):
        for i, (_, _, month, year) in enumerate(column):
            entries = [" ".join(parts) for parts in blocks[(side, i)]]
            out.append(f"{_MONTH_NAMES[month - 1]} {year}:\n" + ("\n".join(entries) if entries else "(no entries)"))
    return "\n\n".join(out)


_PLAIN_PROMPT = (
    "This is a school district's school-year calendar. Record every dated entry in the event list "
    "(closures, recesses, early dismissals, delayed openings, first and last student day, conferences, holidays). "
    "A range like '26-27 Thu-Fri' is one entry from the 26th to the 27th; a month-header above the list gives the month, "
    "and the school year in the title gives the year (fall months are the first year, January-June the second). "
    "Do NOT record the mini month grids, the days-in-session table or the key. Do not record the emergency/snow make-up "
    "day list. Only mark an entry 'closed' if the printed text says schools are closed."
)


async def extract_events(pdf_bytes: bytes) -> list[dict]:
    if not ANTHROPIC_API_KEY:
        return []
    client = AsyncAnthropic(api_key=ANTHROPIC_API_KEY)
    started = time.perf_counter()
    by_month = layout_text_by_month(pdf_bytes)
    if by_month:
        content = [
            {
                "type": "text",
                "text": "This is a school district's school-year calendar, already split by month: each 'MONTH YYYY:' heading is "
                "followed by that month's printed event list, in the month the heading says (the year is part of the heading). "
                "Record every dated entry (closures, recesses, early dismissals, delayed openings, first and last student day, "
                "conferences, holidays, trips). A range like '26-31' is one entry from the 26th to the 31st of THAT heading's month. "
                "Only mark an entry 'closed' if the printed text says closed. A 'Noon Dismissal' is students going home early: "
                "kind early_dismissal, even when it is also a staff in-service day.\n\n" + by_month,
            }
        ]
    else:
        content = [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": base64.b64encode(pdf_bytes).decode("ascii")}},
            {
                "type": "text",
                "text": _PLAIN_PROMPT,
            },
        ]
    response = await client.messages.create(
        model=MODEL,
        max_tokens=8192,
        extra_body={"temperature": 0},
        tools=[_CALENDAR_TOOL],
        tool_choice={"type": "tool", "name": "record_calendar"},
        messages=[{"role": "user", "content": content}],
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
