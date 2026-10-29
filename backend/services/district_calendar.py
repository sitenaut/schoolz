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
import logging
import re
from datetime import UTC, date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup
from dateutil.rrule import rrulestr
from icalendar import Calendar
from icalendar.prop import vRecur

from services import incidentiq

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
# Which occurrences of a recurring event are stored: the same span the
# Apptegy feeds are read over (scheduler/jobs/district_calendar_scan.py).
_RECUR_PAST = timedelta(days=120)
_RECUR_FUTURE = timedelta(days=400)
_MAX_OCCURRENCES = 400


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


def _as_list(value) -> list:
    if value is None:
        return []
    return value if isinstance(value, list) else [value]


def _instant(value) -> datetime:
    """For matching an occurrence to a RECURRENCE-ID or EXDATE however each
    spells its time (a TZID, UTC, or a bare date)."""
    return _as_datetime(value)[0].astimezone(UTC)


def _occurrences(component, start_value) -> list:
    """The starts (date or datetime, like DTSTART) of a recurring VEVENT in
    the stored window: RRULE plus RDATE, minus EXDATE. Read as its master
    alone, a feed's "Early Dismissal - every Wednesday" showed on the first
    Wednesday only. UNTIL is applied here rather than by dateutil, which
    refuses one whose timezone-awareness differs from DTSTART's - and feeds
    write a UTC UNTIL for an all-day series."""
    all_day = not isinstance(start_value, datetime)
    anchor = datetime.combine(start_value, time.min) if all_day else start_value

    def like_anchor(value) -> datetime:
        if not isinstance(value, datetime):
            value = datetime.combine(value, time.min)
        if anchor.tzinfo is None:
            return value.astimezone(_ET).replace(tzinfo=None) if value.tzinfo else value
        return value if value.tzinfo else value.replace(tzinfo=_ET)

    now = like_anchor(datetime.now(_ET))
    first, last = now - _RECUR_PAST, now + _RECUR_FUTURE

    found: list[datetime] = []
    for recur in _as_list(component.get("RRULE")):
        parts = dict(recur)
        until = (parts.pop("UNTIL", None) or [None])[0]
        if until is not None and not isinstance(until, datetime):
            until = datetime.combine(until, time.max)  # an UNTIL date includes that whole day
        stop = like_anchor(until) if until is not None else None
        rule = rrulestr(vRecur(parts).to_ical().decode(), dtstart=anchor)
        for occ in rule.xafter(first, count=_MAX_OCCURRENCES, inc=True):
            if occ > last or (stop is not None and occ > stop):
                break
            found.append(occ)
    for rdate in _as_list(component.get("RDATE")):
        for d in rdate.dts:
            value = d.dt[0] if isinstance(d.dt, tuple) else d.dt  # a PERIOD starts the occurrence
            occ = like_anchor(value)
            if first <= occ <= last:
                found.append(occ)
    excluded = {_instant(d.dt) for exdate in _as_list(component.get("EXDATE")) for d in exdate.dts}
    out, seen = [], set()
    for occ in sorted(found):
        value = occ.date() if all_day else occ
        key = _instant(value)
        if key in excluded or key in seen:
            continue
        seen.add(key)
        out.append(value)
    return out


def _cancelled(component) -> bool:
    return str(component.get("STATUS") or "").upper() == "CANCELLED"


def _stable_uid(uid: str | None, title: str, dt: datetime) -> str:
    if uid:
        return uid
    digest = hashlib.sha1(f"{title}|{dt.isoformat()}".encode()).hexdigest()
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
    end_date, is_all_day} dicts, one per VEVENT. An Incident IQ feed key
    (Pine Hill's facilities calendars) is routed to its own adapter."""
    if incidentiq.is_incidentiq_feed(ics_url):
        return await incidentiq.fetch_events(ics_url, timeout)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.get(ics_url, headers={"User-Agent": "schoolz-district-calendar/1.0"})
        resp.raise_for_status()
        body = resp.content

    try:
        cal = Calendar.from_ical(body)
    except Exception as exc:  # noqa: BLE001
        logger.warning("district_calendar_parse_failed", extra={"url": ics_url, "error": str(exc)})
        return []

    # Occurrences a series' own override VEVENT replaces (moved, edited or
    # cancelled): the override stands in for them.
    overridden: set[tuple[str, datetime]] = set()
    for component in cal.walk("VEVENT"):
        recurrence_id = component.get("RECURRENCE-ID")
        if component.get("UID") and recurrence_id is not None:
            try:
                overridden.add((str(component.get("UID")), _instant(recurrence_id.dt)))
            except Exception:  # noqa: BLE001
                pass

    regenerated_uids = "/sndreq/generateCalendarICS.php" in ics_url
    out: list[dict] = []
    for component in cal.walk("VEVENT"):
        try:
            if _cancelled(component):
                continue
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
            # Smart Sites' generated feed mints every UID afresh each time it
            # rebuilds the file (Palmyra: PHP uniqid, every few hours), which
            # would retire and re-add every row; key those on title and start.
            uid = str(component.get("UID")) if component.get("UID") and not regenerated_uids else None
            # A moved/edited instance of a recurring series is its own VEVENT
            # carrying the series' UID plus a RECURRENCE-ID. Keyed on the UID
            # alone it collides with the master (Woodbury's board meeting
            # showed twice), so the instance is keyed by the occurrence it
            # replaces.
            recurrence_id = component.get("RECURRENCE-ID")
            if uid and recurrence_id is not None:
                uid = f"{uid}#{_as_datetime(recurrence_id.dt)[0].isoformat()}"

            starts = [dtstart.dt]
            if recurrence_id is None and component.get("RRULE") is not None:
                starts = _occurrences(component, dtstart.dt)
            for value in starts:
                occ_start, _ = _as_datetime(value)
                if uid and recurrence_id is None and (uid, _instant(value)) in overridden:
                    continue
                # The first occurrence keeps the series' UID, so a row stored
                # before recurrences were read stays the same row; the rest
                # are keyed like an override of that occurrence would be.
                occ_uid = uid if occ_start == start or not uid else f"{uid}#{occ_start.isoformat()}"
                out.append(
                    {
                        "external_uid": _stable_uid(occ_uid, title, occ_start),
                        "title": title[:300],
                        "description": description,
                        "start_date": occ_start,
                        "end_date": end + (occ_start - start) if end is not None else None,
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
