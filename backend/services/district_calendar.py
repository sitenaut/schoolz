"""Fetches and parses a district's own events calendar (.ics feed) -
holidays, early dismissals, in-service days, and other office/school
closures. Confirmed real (Cherry Hill Public Schools): the calendar page
itself never renders a plain link to this feed - the "Subscribe to
calendar" button's URL is only ever handed to `navigator.clipboard.
writeText()` by the page's own JS, not present anywhere in the DOM/HTML.
Found by scripting a real browser click and intercepting that clipboard
write (see git history / notes for the discovery script) rather than
reverse-engineering the endpoint by guessing paths.

Ported from billz's `backend/events/sources/ical.py` (its generic local-
events ICS adapter) - same timezone-anchoring fix, same approach, applied
here to one specific district feed instead of many general-purpose ones.
"""

import hashlib
import re
import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from icalendar import Calendar

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _as_datetime(value) -> tuple[datetime | None, bool]:
    """Coerce an iCal DATE/DATETIME into a tz-aware datetime, returning
    (value, is_all_day).

    A bare iCal DATE (all-day event - "DISTRICT CLOSED", "FIRST DAY OF
    SCHOOL") has no timezone of its own - it's a floating calendar date.
    Anchoring it to UTC midnight is wrong: converted back to America/
    New_York for display, that lands on the *previous* local day. Anchor
    to ET midnight instead - the same off-by-one class of bug already
    fixed once in this codebase for Smore/lunch-menu dates
    (content_extractor.py:_parse_date)."""
    if value is None:
        return None, False
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=_ET)), False
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=_ET), True
    return None, False


def _stable_uid(uid: str | None, title: str, dt: datetime) -> str:
    if uid:
        return uid
    digest = hashlib.sha1(f"{title}|{dt.isoformat()}".encode("utf-8")).hexdigest()
    return f"hash:{digest[:24]}"


_TAG_RE = re.compile(r"</?[a-zA-Z][^>]*>")
_BLOCK_TAGS = ("p", "div", "li", "ul", "ol", "h1", "h2", "h3", "h4", "tr")


def description_text(raw: str | None) -> str | None:
    """Plain text for a VEVENT DESCRIPTION.

    Google Calendar stores a description edited in its rich-text box as
    HTML and exports it verbatim - confirmed on Cherry Hill East's school
    calendar, where "PSAT DAY" arrived as `...all<i> </i><b><i>10</i></b>
    <b><i>th </i></b>...` and the tags showed up literally on the page.
    Plain-text descriptions pass through untouched (only trimmed). Line
    breaks are kept - the frontend renders descriptions with pre-line.
    """
    text = (raw or "").strip()
    if not text:
        return None
    if not _TAG_RE.search(text):
        return text
    soup = BeautifulSoup(text, "html.parser")
    for br in soup.find_all("br"):
        br.replace_with("\n")
    for a in soup.find_all("a", href=True):
        # Keep the destination when the link text doesn't already show it,
        # since the text alone ("Sign up here") is useless without the href.
        label = a.get_text().strip()
        href = a["href"].strip()
        if href and href not in label and not href.startswith("mailto:"):
            a.replace_with(f"{label} ({href})" if label else href)
    for el in soup.find_all(_BLOCK_TAGS):
        el.insert_before("\n")
        el.insert_after("\n")
    lines = [" ".join(line.replace("\xa0", " ").split()) for line in soup.get_text().split("\n")]
    cleaned = re.sub(r"\n{3,}", "\n\n", "\n".join(lines)).strip()
    return cleaned or None


async def fetch_district_calendar(ics_url: str, timeout: float = 30.0) -> list[dict]:
    """Returns a list of {external_uid, title, description, start_date,
    end_date, is_all_day} dicts, one per VEVENT."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(ics_url, headers={"User-Agent": "schoolz-district-calendar/1.0"})
        resp.raise_for_status()
        body = resp.content

    try:
        cal = Calendar.from_ical(body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("district_calendar_parse_failed", extra={"url": ics_url, "error": str(exc)})
        return []

    out: list[dict] = []
    for component in cal.walk("VEVENT"):
        try:
            dtstart = component.get("DTSTART")
            if dtstart is None:
                continue
            start, is_all_day = _as_datetime(dtstart.dt)
            if start is None:
                continue
            dtend = component.get("DTEND")
            end, _ = _as_datetime(dtend.dt) if dtend is not None else (None, False)

            title = str(component.get("SUMMARY") or "").strip() or "(untitled)"
            description = description_text(str(component.get("DESCRIPTION") or ""))
            uid = str(component.get("UID")) if component.get("UID") else None

            out.append(
                {
                    "external_uid": _stable_uid(uid, title, start),
                    "title": title[:300],
                    "description": description,
                    "start_date": start,
                    "end_date": end,
                    "is_all_day": is_all_day,
                }
            )
        except Exception as exc:  # noqa: BLE001
            logger.warning("district_calendar_vevent_skipped", extra={"url": ics_url, "error": str(exc)})
            continue
    return out


_GRADE_SPAN_RE = re.compile(
    r"(?:\(|\bgrades?\s+)\s*(pre-?k|pk|preschool|k|\d{1,2})\s*[-–]\s*(\d{1,2})\b",
    re.I,
)
# (lowest grade, highest grade, school type); preschool is grade -1.
_TYPE_GRADES = [(-1, -1, "other"), (0, 5, "elementary"), (6, 8, "middle"), (9, 12, "high"), (9, 12, "alternative")]


def school_types_from_title(title: str) -> list[str] | None:
    """School types a district-wide feed event is really scoped to, when its
    title names a grade span - confirmed real: "STUDENT EARLY DISMISSAL
    (PRESCHOOL-8): Pre-K, Elementary, and Middle Conferences" sits on the
    main district feed with no type filter, so both high schools showed an
    early dismissal all conference week. Only a parenthesised span or one
    after "Grade(s)" counts, so a stray number pair can't narrow a closure."""
    m = _GRADE_SPAN_RE.search(title or "")
    if not m:
        return None
    lo_raw, hi = m.group(1).lower(), int(m.group(2))
    lo = -1 if lo_raw.startswith("p") else 0 if lo_raw == "k" else int(lo_raw)
    if hi < lo or hi > 12:
        return None
    types = [t for g_lo, g_hi, t in _TYPE_GRADES if g_lo <= hi and lo <= g_hi]
    return types or None
