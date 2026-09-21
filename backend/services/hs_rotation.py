"""High school day-rotation parser.

Cherry Hill's two high schools run the same 6-day A–H block rotation, and
the district publishes one shared "2026-27 East and West Day Schedule"
PDF (a Google Sheets export) linked from West's "CHW Day Schedule" nav
page. East's own "Day/Test Calendar" page is a per-month events-calendar
image whose DAY labels match this PDF exactly (confirmed Sep 2026), so
this one source covers both schools.

Layout: two or three month columns side by side, each a list of
"<day>-Day <value>" rows, where value is a rotation number ("3",
"1 - Cycle 10 (Early Dismissal)", "6 - STAR GAMES"), or a non-rotation
note ("No School Labor Day", "Teacher In-Service Day (Lunar NY)",
"PSAT DAY Early Dismissal(?)", "Final Exam Day (A/B) Early Dismissal").
Parsed deterministically from word coordinates (pdfplumber): month
headers set each column's current month, and every entry is assigned to
the column it sits under. The sheet is marked "Tentative - update as
needed", hence the 12h rescan and the delete-what-disappeared upsert in
the job.
"""

import io
import re
from datetime import date

import pdfplumber

from scheduler.errors import record_parse_issue

MONTHS = {
    "september": 9, "october": 10, "november": 11, "december": 12,
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7, "august": 8,
}
_TITLE_YEAR_RE = re.compile(r"(20\d{2})\s*-\s*(20\d{2})")
_DAY_TOKEN_RE = re.compile(r"^(\d{1,2})-?(Day)?$", re.I)
_ROTATION_RE = re.compile(r"^(\d)\b")
_CYCLE_RE = re.compile(r"cycle\s*(\d+)", re.I)
_EARLY_RE = re.compile(r"early\s+dismissal", re.I)
_CLOSED_RE = re.compile(r"no\s+school|in-service|inservice", re.I)
_LEGEND_RE = re.compile(r"Day\s*(\d)\s*=\s*([A-H](?:\s*,\s*[A-H])*)", re.I)


def parse_rotation_pdf(data: bytes) -> dict:
    """Returns {"academic_year": "2026-2027", "blocks": {1: ["A","B",...]},
    "days": [{"date", "day_number", "cycle", "early_dismissal", "closed",
    "note"}]} - one entry per calendar row in the sheet."""
    days: dict[date, dict] = {}
    blocks: dict[int, list[str]] = {}
    start_year = end_year = None

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if start_year is None:
                m = _TITLE_YEAR_RE.search(text)
                if m:
                    start_year, end_year = int(m.group(1)), int(m.group(2))
            for m in _LEGEND_RE.finditer(text):
                blocks.setdefault(int(m.group(1)), [b.strip() for b in m.group(2).split(",")])

            words = page.extract_words(keep_blank_chars=False, use_text_flow=False)
            # Group into lines by vertical position.
            lines: dict[int, list] = {}
            for w in words:
                lines.setdefault(round(w["top"] / 3), []).append(w)
            # Column anchors: x0 of each month header, discovered as we go.
            col_month: dict[float, int] = {}

            def column_for(x: float) -> float | None:
                # Nearest month header horizontally - entries sit slightly
                # left of their header (header is centered over the column).
                return min(col_month, key=lambda cx: abs(cx - x)) if col_month else None

            for _, line_words in sorted(lines.items()):
                line_words.sort(key=lambda w: w["x0"])
                # A month header can share a line with another column's
                # entry ("31-Day 5   June", "April   2-Day 2"), so headers
                # are peeled off first and the rest parsed as entries.
                headers = [w for w in line_words if w["text"].strip().lower() in MONTHS]
                for h in headers:
                    # Snap to an existing anchor if this header sits in the
                    # same column as an earlier one (Sep -> Oct).
                    existing = [cx for cx in col_month if abs(cx - h["x0"]) < 60]
                    key = existing[0] if existing else h["x0"]
                    col_month[key] = MONTHS[h["text"].strip().lower()]
                line_words = [w for w in line_words if w not in headers]
                if not col_month or not line_words:
                    continue

                def day_token_at(idx: int) -> tuple[int, int] | None:
                    """A row starts with "8-Day", "11Day", or "3-"/"3" followed
                    by a separate "Day" token. A bare digit with no "Day"
                    after it is a rotation *value*, not a new row."""
                    m = _DAY_TOKEN_RE.match(line_words[idx]["text"])
                    if not m:
                        return None
                    if m.group(2):
                        return int(m.group(1)), idx + 1
                    if idx + 1 < len(line_words) and line_words[idx + 1]["text"].lower() == "day":
                        return int(m.group(1)), idx + 2
                    return None

                # Split the line into (day_number, tokens) entries.
                i = 0
                while i < len(line_words):
                    hit = day_token_at(i)
                    if not hit:
                        i += 1
                        continue
                    day_of_month, j = hit
                    x = line_words[i]["x0"]
                    value_tokens = []
                    while j < len(line_words) and not day_token_at(j):
                        value_tokens.append(line_words[j]["text"])
                        j += 1
                    col = column_for(x)
                    month = col_month.get(col) if col is not None else None
                    if month and start_year:
                        year = start_year if month >= 7 else (end_year or start_year + 1)
                        try:
                            d = date(year, month, day_of_month)
                        except ValueError:
                            d = None
                        if d:
                            days[d] = _classify(" ".join(value_tokens))
                            days[d]["date"] = d.isoformat()
                    else:
                        record_parse_issue(
                            "hs_rotation.scan", "unexpected_format",
                            sample=" ".join(w["text"] for w in line_words)[:200],
                        )
                    i = j

    return {
        "academic_year": f"{start_year}-{end_year}" if start_year else None,
        "blocks": blocks,
        "days": [days[k] for k in sorted(days)],
    }


def _classify(value: str) -> dict:
    value = value.strip()
    rot = _ROTATION_RE.match(value)
    cycle = _CYCLE_RE.search(value)
    day_number = int(rot.group(1)) if rot and 1 <= int(rot.group(1)) <= 6 else None
    closed = bool(_CLOSED_RE.search(value)) and day_number is None
    return {
        "day_number": day_number,
        "cycle": int(cycle.group(1)) if cycle else None,
        "early_dismissal": bool(_EARLY_RE.search(value)),
        "closed": closed,
        "note": value or None,
    }


BLOCKS_PREFIX = "Blocks "
_BLOCKS_DESC_RE = re.compile(r"Blocks\s+([A-H](?:\s*,\s*[A-H])*)")


def blocks_from_description(description: str | None) -> list[str] | None:
    """Reads back the letter list hs_rotation_scan writes into each "Day N"
    item's description ("Blocks A, B, E, F · Cycle 2")."""
    m = _BLOCKS_DESC_RE.search(description or "")
    return [b.strip() for b in m.group(1).split(",")] if m else None


_PDF_LINK_RE = re.compile(r"\.pdf($|\?)", re.I)


def find_pdf_link(html: str, base_url: str) -> str | None:
    """First PDF link inside the page's own content area (Finalsite's
    <main id="fsPageContent">), which is all the West nav page holds."""
    from bs4 import BeautifulSoup

    soup = BeautifulSoup(html, "lxml")
    container = soup.find(id="fsPageContent") or soup
    for a in container.find_all("a", href=True):
        href = a["href"]
        if _PDF_LINK_RE.search(href):
            return base_url.rstrip("/") + href if href.startswith("/") else href
    return None
