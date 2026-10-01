"""N-day rotation "cycle calendar" PDF parser (Medford Lakes).

A district-published sheet, one page, titled like "2026-2027 6 Day Cycle
Calendar": month grids in two columns (Sep-Jan left, Feb-Jun right), five
weekday columns each. Every week is *two* rows - the calendar dates, then
directly beneath them each school day's rotation digit, or an `X` where
there is no school. Digits advance 1..N across school days, skipping X.

Parsed from word coordinates (pdfplumber), not text order: the two month
columns interleave line-by-line in extracted text, so only position says
which month a date belongs to. A date's weekday column is its nearest
weekday letter; its digit sits ~15pt to the right of the date, so that is
shifted back before the same nearest-column match.
"""

import io
import re
from datetime import date

import pdfplumber

from scheduler.errors import record_parse_issue
from services.hs_rotation import MONTHS

_TITLE_YEAR_RE = re.compile(r"(20\d{2})\s*-\s*(20\d{2})")
_CYCLE_LEN_RE = re.compile(r"(\d)\s*-?\s*Day\s+Cycle", re.I)
_VALUE_OFFSET = 15
_ROW_GAP = 4


def _nearest(anchors: list[float], x: float) -> int:
    return min(range(len(anchors)), key=lambda i: abs(anchors[i] - x))


def _rows(words: list[dict]) -> list[list[dict]]:
    rows: list[list[dict]] = []
    last_top = None
    for w in sorted(words, key=lambda w: w["top"]):
        if last_top is None or w["top"] - last_top > _ROW_GAP:
            rows.append([])
        rows[-1].append(w)
        last_top = w["top"]
    return rows


def parse_cycle_pdf(data: bytes) -> dict:
    """Returns {"academic_year": "2026-2027", "cycle_length": 6, "days":
    [{"date": "2026-09-01", "day_number": 1 | None, "closed": bool}]} -
    one entry per weekday printed on the sheet."""
    days: dict[date, dict] = {}
    start_year = end_year = cycle_length = None

    with pdfplumber.open(io.BytesIO(data)) as pdf:
        for page in pdf.pages:
            text = page.extract_text() or ""
            if start_year is None:
                m = _TITLE_YEAR_RE.search(text)
                if m:
                    start_year, end_year = int(m.group(1)), int(m.group(2))
                m = _CYCLE_LEN_RE.search(text)
                if m:
                    cycle_length = int(m.group(1))
            if start_year is None:
                continue

            words = page.extract_words()
            headers = [w for w in words if w["text"].strip().lower() in MONTHS]
            letters = [w for w in words if w["text"] in ("M", "T", "W", "F")]

            for h in headers:
                month = MONTHS[h["text"].strip().lower()]
                hx = (h["x0"] + h["x1"]) / 2
                # This block's weekday letters: the first letter row under the header.
                row = sorted((w for w in letters if h["top"] < w["top"] < h["top"] + 25), key=lambda w: w["x0"])
                groups: list[list[dict]] = []
                for w in row:
                    if groups and w["x0"] - groups[-1][-1]["x0"] < 38:
                        groups[-1].append(w)
                    else:
                        groups.append([w])
                # Month headers aren't centered over their grid, so take the
                # letter group nearest the header, not the one it sits within.
                below = min(groups, key=lambda g: abs((g[0]["x0"] + g[-1]["x0"]) / 2 - hx), default=[])
                below.sort(key=lambda w: w["x0"])
                anchors = [w["x0"] for w in below]
                letters_top = below[0]["top"]
                # The block ends where the next header in the same column starts.
                later = [o["top"] for o in headers if o["top"] > h["top"] and abs((o["x0"] + o["x1"]) / 2 - hx) < 60]
                bottom = min(later) if later else page.height
                lo, hi = anchors[0] - 12, anchors[-1] + _VALUE_OFFSET + 20
                body = [
                    w for w in words
                    if letters_top + 3 < w["top"] < bottom - 1 and lo <= w["x0"] <= hi and re.fullmatch(r"\d{1,2}|X", w["text"])
                ]
                rows = _rows(body)
                if len(rows) % 2:
                    record_parse_issue("cycle_calendar.scan", "unexpected_format", sample=f"{h['text']}: odd number of rows ({len(rows)})")
                    rows = rows[:-1]
                year = start_year if month >= 7 else end_year
                for date_row, value_row in zip(rows[0::2], rows[1::2]):
                    values: dict[int, str] = {}
                    for v in value_row:
                        values[_nearest(anchors, v["x0"] - _VALUE_OFFSET)] = v["text"]
                    for dw in date_row:
                        if not dw["text"].isdigit():
                            continue
                        raw = values.get(_nearest(anchors, dw["x0"]))
                        try:
                            d = date(year, month, int(dw["text"]))
                        except ValueError:
                            continue
                        if raw is None:
                            record_parse_issue("cycle_calendar.scan", "unexpected_format", sample=f"{d.isoformat()}: no value under date")
                            continue
                        closed = raw == "X"
                        days[d] = {"date": d.isoformat(), "day_number": None if closed else int(raw), "closed": closed}

    ordered = [days[k] for k in sorted(days)]
    if cycle_length:
        prev = None
        for d in ordered:
            if d["closed"]:
                continue
            if prev is not None and d["day_number"] != prev % cycle_length + 1:
                record_parse_issue("cycle_calendar.scan", "cycle_sequence_break", sample=f"{d['date']}: Day {d['day_number']} after Day {prev}")
            prev = d["day_number"]

    return {
        "academic_year": f"{start_year}-{end_year}" if start_year else None,
        "cycle_length": cycle_length,
        "days": ordered,
    }
