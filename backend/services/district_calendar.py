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
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
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
            description = str(component.get("DESCRIPTION") or "").strip() or None
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
