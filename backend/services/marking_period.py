"""Parses the district's "Conferences, Interim and Report Card Dates" page
into structured per-school-type deadlines. Deliberately a plain HTML table
parser, not an LLM extraction pass - confirmed real: the page renders these
as genuine `<table>` elements with a clean header row (e.g. "Interims
Issued" / "Marking Period Ends" / "Report Card Dates"), one table per
school tier (High School, Middle School, Grades K-5, Preschool), preceded
by an all-caps `<p>` heading naming the tier - reliable enough to parse
deterministically rather than risk an LLM mis-zipping which date belongs
to which column.
"""

import asyncio
import io
import re
from datetime import datetime
from urllib.parse import quote, urljoin, urlparse
from zoneinfo import ZoneInfo

import httpx
import pdfplumber
from bs4 import BeautifulSoup

import scraper_client
from scheduler.errors import record_parse_issue
from services.presence_documents import list_page_documents

_ET = ZoneInfo("America/New_York")

# Maps the page's own all-caps section heading to School.school_type -
# whichever heading most recently preceded a <table> in document order.
_HEADING_TO_SCHOOL_TYPE = {
    "HIGH SCHOOL": "high",
    "MIDDLE SCHOOL": "middle",
    "GRADES K-5 INTERIM AND REPORT CARD SCHEDULE": "elementary",
    "PRESCHOOL REPORT CARD SCHEDULE": "other",
}

_SCHOOL_TYPE_LABEL = {"high": "High School", "middle": "Middle School", "elementary": "Elementary", "other": "Preschool"}


def _parse_date_text(text: str) -> datetime | None:
    # Confirmed real: one cell reads "June 17, 2027*available at 4:00 p.m."
    # - a footnote marker followed by trailing text, not just a bare
    # trailing asterisk - drop everything from the first "*" onward.
    text = text.split("*")[0].strip()
    # Confirmed real: the preschool table's dates are weekday-prefixed
    # ("Monday, November 30, 2026") while every other table's aren't
    # ("October 14, 2026") - try both.
    for fmt in ("%B %d, %Y", "%b %d, %Y", "%A, %B %d, %Y", "%a, %b %d, %Y"):
        try:
            return datetime.strptime(text, fmt).replace(tzinfo=_ET)
        except ValueError:
            continue
    return None


def parse_marking_period_page(html: str) -> list[dict]:
    """Returns a list of {school_type, title, start_date, external_uid}."""
    soup = BeautifulSoup(html, "lxml")
    main = soup.find(id="fsPageContent") or soup

    results: list[dict] = []
    current_school_type: str | None = None
    for el in main.descendants:
        if getattr(el, "name", None) == "p":
            # Confirmed real: the "PRESCHOOL REPORT CARD SCHEDULE" heading
            # uses a non-breaking space between the first two words, which
            # silently fails an exact dict-key match otherwise.
            text = " ".join(el.get_text(strip=True).split())
            if text in _HEADING_TO_SCHOOL_TYPE:
                current_school_type = _HEADING_TO_SCHOOL_TYPE[text]
            continue

        if getattr(el, "name", None) != "table":
            continue
        if not current_school_type:
            record_parse_issue("marking_period.scan", "no_matches", selector="table heading")
            continue

        rows = el.find_all("tr")
        if not rows:
            continue
        headers = [td.get_text(strip=True) for td in rows[0].find_all("td")]
        for row in rows[1:]:
            cells = [td.get_text(strip=True) for td in row.find_all("td")]
            for header, cell_text in zip(headers, cells):
                start_date = _parse_date_text(cell_text)
                if not start_date:
                    continue
                label = _SCHOOL_TYPE_LABEL.get(current_school_type, current_school_type)
                results.append(
                    {
                        "school_type": current_school_type,
                        "title": f"{label}: {header}",
                        "start_date": start_date,
                        "external_uid": f"marking_period:{current_school_type}:{header}:{start_date.date().isoformat()}",
                    }
                )
        # Each school type's table is consumed once - clear so a later
        # table without its own heading (shouldn't happen, but be safe)
        # doesn't get double-attributed to this same type.
        current_school_type = None

    return results


_YEAR_RE = re.compile(r"(\d{4})\s*-\s*(\d{4})\s+School Calendar", re.IGNORECASE)
_PDF_ENDS_RE = re.compile(r"(\d)(?:st|nd|rd|th)\s+Marking Period Ends\s*-\s*(\d{1,2})/(\d{1,2})", re.IGNORECASE)
_PDF_GRADES_RE = re.compile(r"Final Q(\d)\s+Grades Posted\s*-\s*(\d{1,2})/(\d{1,2})", re.IGNORECASE)
_PDF_INTERIM_RE = re.compile(r"INTERIM REPORTS.{0,300}?Dates:\s*((?:\d{1,2}/\d{1,2}(?:,\s*)?)+)", re.IGNORECASE | re.DOTALL)


_FULL = r"(\d{1,2})/(\d{1,2})/(\d{2})"
_PDF_RANGE_RE = re.compile(r"(\d)(?:st|nd|rd|th):\s*" + _FULL + r"\s*-\s*" + _FULL)
_PDF_PAIR_RE = re.compile(_FULL + r"\s+" + _FULL)
_LONG_DATE_RE = re.compile(r"(January|February|March|April|May|June|July|August|September|October|November|December)\s+(\d{1,2}),\s*(\d{4})")
_MONTHS = {m: i for i, m in enumerate(["January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December"], 1)}


def _entry(title: str, start: datetime) -> dict:
    return {"school_type": None, "title": title, "start_date": start, "external_uid": f"marking_period:pdf:{title}:{start.date().isoformat()}"}


def _full_date(mo: str, d: str, yy: str) -> datetime | None:
    try:
        return datetime(2000 + int(yy), int(mo), int(d), tzinfo=_ET)
    except ValueError:
        return None


def parse_calendar_pdf_dated(text: str) -> list[dict]:
    """Calendar PDFs that print full dates: a "1st: 9/2/26-11/11/26" list of
    marking periods (Stratford, four; Laurel Springs, three trimesters), plus
    Stratford's INTERIMS / REPORT CARDS columns ("10/7/26 11/18/26" per row)
    and Laurel Springs' REPORT CARDS list ("December 11, 2026", ...)."""
    out: list[dict] = []
    unit = "Trimester" if re.search(r"TRIMESTER\s+MARKING\s+PERIODS", text, re.I) else "Marking Period"
    for m in _PDF_RANGE_RE.findall(text):
        when = _full_date(*m[4:7])
        if when:
            out.append(_entry(f"{unit} {m[0]} Ends", when))

    cols = re.search(r"INTERIMS\s+REPORT CARDS", text)
    if cols:
        stop = re.search(r"MARKING\s+PERIODS", text[cols.end():])
        segment = text[cols.end(): cols.end() + (stop.start() if stop else 600)]
        for m in _PDF_PAIR_RE.findall(segment):
            for title, parts in (("Interim Reports Issued", m[:3]), ("Report Cards Issued", m[3:])):
                when = _full_date(*parts)
                if when:
                    out.append(_entry(title, when))
    else:
        head = re.search(r"REPORT CARDS", text)
        if head:
            stop = re.search(r"TRIMESTER\s+MARKING\s+PERIODS|MARKING\s+PERIODS", text[head.end():])
            segment = text[head.end(): head.end() + (stop.start() if stop else 400)]
            for mon, d, y in _LONG_DATE_RE.findall(segment):
                try:
                    out.append(_entry("Report Cards Issued", datetime(int(y), _MONTHS[mon], int(d), tzinfo=_ET)))
                except ValueError:
                    continue
    return out


# Pine Hill: one block per school level, labels on one line and their date
# ranges on the next ("1st MP 2nd MP" / "9/1/26 - 11/4/26 11/9/26 -1/27/27"),
# with the calendar's legend glued onto the same lines.
_GRID_HEADING_RE = re.compile(r"^(.*?)\s*Marking Period Dates", re.IGNORECASE)
_GRID_LABEL_RE = re.compile(r"(\d)(?:st|nd|rd|th)\s+MP\b", re.IGNORECASE)
_GRID_RANGE_RE = re.compile(_FULL + r"\s*-\s*" + _FULL)


def _grid_school_types(heading: str) -> list[str]:
    """"PHMS/OHS" -> middle + high; a block named for buildings
    ("Glenn/Bean") has no level word and is the elementary schools."""
    types = []
    for token in re.split(r"[/&,]|\band\b", heading):
        token = token.strip().upper()
        if not token:
            continue
        if token.endswith("HS") or "HIGH" in token:
            kind = "high"
        elif token.endswith("MS") or "MIDDLE" in token:
            kind = "middle"
        else:
            kind = "elementary"
        if kind not in types:
            types.append(kind)
    return types


def parse_marking_period_grid(text: str) -> list[dict]:
    blocks: list[tuple[list[str], list[tuple[int, datetime]]]] = []
    pending: list[int] = []
    for line in text.splitlines():
        heading = _GRID_HEADING_RE.match(line.strip())
        if heading:
            blocks.append((_grid_school_types(heading.group(1)), []))
            pending = []
            continue
        if not blocks:
            continue
        labels = [int(n) for n in _GRID_LABEL_RE.findall(line)]
        if labels:
            pending = labels
            continue
        ranges = _GRID_RANGE_RE.findall(line)
        if pending and ranges:
            for number, parts in zip(pending, ranges):
                end = _full_date(*parts[3:6])
                if end:
                    blocks[-1][1].append((number, end))
            pending = []
    out = []
    for types, periods in blocks:
        unit = "Trimester" if len(periods) == 3 else "Marking Period"
        for number, end in periods:
            for kind in types:
                title = f"{unit} {number} Ends"
                out.append(
                    {
                        "school_type": kind,
                        "title": title,
                        "start_date": end,
                        "external_uid": f"marking_period:pdf:{kind}:{title}:{end.date().isoformat()}",
                    }
                )
    return out


def parse_calendar_pdf_text(text: str) -> list[dict]:
    """Marking-period dates printed in a school-year calendar PDF's sidebar
    ("1st Marking Period Ends - 11/4 (44 days)", "Final Q1 Grades Posted -
    11/11", "INTERIM REPORTS Dates: 10/2, 12/11, ..."). Dates carry no year, so
    it comes from the "2026-2027 School Calendar" title: July-December is the
    first year, January-June the second. School-wide (no school_type). Falls
    through to the full-date layouts (`parse_calendar_pdf_dated`)."""
    return _parse_sidebar_pdf(text) or parse_calendar_pdf_dated(text) or parse_marking_period_grid(text)


def _parse_sidebar_pdf(text: str) -> list[dict]:
    year_m = _YEAR_RE.search(text)
    if not year_m:
        return []
    first, second = int(year_m.group(1)), int(year_m.group(2))

    def when(month: str, day: str) -> datetime | None:
        m, d = int(month), int(day)
        try:
            return datetime(first if m >= 7 else second, m, d, tzinfo=_ET)
        except ValueError:
            return None

    out: list[dict] = []

    def add(title: str, month: str, day: str) -> None:
        start = when(month, day)
        if start:
            out.append({"school_type": None, "title": title, "start_date": start, "external_uid": f"marking_period:pdf:{title}:{start.date().isoformat()}"})

    for n, mo, d in _PDF_ENDS_RE.findall(text):
        add(f"Marking Period {n} Ends", mo, d)
    for n, mo, d in _PDF_GRADES_RE.findall(text):
        add(f"Quarter {n} Report Card Grades Posted", mo, d)
    interim = _PDF_INTERIM_RE.search(text)
    for pair in re.findall(r"\d{1,2}/\d{1,2}", interim.group(1)) if interim else []:
        mo, d = pair.split("/")
        add("Interim Reports Issued", mo, d)
    return out


def _pdf_text(data: bytes) -> str:
    with pdfplumber.open(io.BytesIO(data)) as pdf:
        return "\n".join(page.extract_text() or "" for page in pdf.pages)


async def _presence_calendar_dates(url: str) -> list[dict] | None:
    """For a Presence site (documents load client-side, so the scraper's HTML
    holds none): read the calendar PDF out of the page's documents widget.
    None when the page isn't Presence, so the table path runs."""
    try:
        docs = await list_page_documents(url)
    except httpx.HTTPError:
        return None
    if not docs:
        return None
    pdfs = [d for d in docs if d["extension"] == "pdf" and "calendar" in d["title"].lower()]
    if not pdfs:
        return []
    async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers={"User-Agent": "Mozilla/5.0 (schoolz calendar sync)"}) as client:
        resp = await client.get(pdfs[0]["url"])
        resp.raise_for_status()
    return parse_calendar_pdf_text(await asyncio.to_thread(_pdf_text, resp.content))


def find_calendar_pdf(html: str, page_url: str) -> str | None:
    """The school-year calendar PDF linked from a page (Stratford's home page,
    Laurel Springs' calendar page): a .pdf whose link text or name says calendar.
    A page that still links last year's beside this year's (Pine Hill) gets the
    one whose name carries the latest year; ties keep page order."""
    soup = BeautifulSoup(html, "lxml")
    found: list[tuple[int, str]] = []
    for a in soup.find_all("a", href=True):
        href = urljoin(page_url, a["href"].strip())
        if urlparse(href).path.lower().endswith(".pdf") and "calendar" in (a.get_text(" ", strip=True) + href).lower():
            years = [int(y) for y in re.findall(r"(?<!\d)(20\d{2})(?!\d)", urlparse(href).path.rsplit("/", 1)[-1])]
            found.append((max(years, default=0), quote(href, safe=":/%?=&")))
    if not found:
        return None
    best = max(year for year, _ in found)
    return next(url for year, url in found if year == best)


async def _pdf_calendar_dates(url: str) -> list[dict]:
    """Dates from a calendar PDF that is the URL itself or is linked from it.
    Empty when there is no such PDF or it has none of the known layouts, so the
    HTML table path still runs."""
    headers = {"User-Agent": "Mozilla/5.0 (schoolz calendar sync)"}
    try:
        async with httpx.AsyncClient(timeout=30, follow_redirects=True, headers=headers) as client:
            resp = await client.get(url)
            resp.raise_for_status()
            if resp.content[:5] != b"%PDF-":
                pdf_url = find_calendar_pdf(resp.text, str(resp.url))
                if not pdf_url:
                    return []
                resp = await client.get(pdf_url)
                resp.raise_for_status()
    except httpx.HTTPError:
        return []
    return parse_calendar_pdf_text(await asyncio.to_thread(_pdf_text, resp.content))


async def fetch_marking_period_page(url: str) -> list[dict]:
    from_pdf = await _presence_calendar_dates(url)
    if from_pdf is not None:
        return from_pdf
    from_pdf = await _pdf_calendar_dates(url)
    if from_pdf:
        return from_pdf
    result = await scraper_client.fetch_html(url, wait_for_selector="table", block_assets=True)

    return parse_marking_period_page(result["html"])

