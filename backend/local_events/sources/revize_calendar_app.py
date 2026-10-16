"""Revize's older calendar (`/calendar_app/`), still on several NJ town sites.

Newer Revize sites serve `_assets_/plugins/revizeCalendar/calendar_data_handler.php`
(the `revize` parser in json_api.py); on these it 404s. The old app is a
2015-era JSP page that loads plain XML published next to it, one file per
calendar per month:

    <site>/calendar_app/db/calendar_<id>_activemonthsdata_<YYYY-MM>.xml

`calendar_app/db/calendar_db_data.xml` lists the calendar ids (1 is "Master";
some towns add e.g. 2 = "Parks and Rec"). A month with no events has no file
(404), which is not an error. The export button's `export_events.jsp` 403s.

Each `<event>` carries `date_begin` ("Oct 3, 2026"), `time_begin` ("19:00",
empty = all day), `duration` ("4hrs", "30mins", "6days"), and - for repeating
or multi-day events - `dates`, every occurrence as MM-DD-YYYY, where a
trailing "+" marks a continuation day of a multi-day event rather than a new
occurrence. A repeating event appears whole in every month file it touches,
so occurrences dedupe on (event id, date).
"""
from __future__ import annotations

import logging
import re
import xml.etree.ElementTree as ET
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")
_DURATION = re.compile(r"(\d+)\s*(min|hr|hour|day)", re.I)
_UA = "Mozilla/5.0 (compatible; schoolz-local-events/1.0)"


def month_file_url(base_url: str, calendar_id: int | str, year: int, month: int) -> str:
    return f"{base_url.rstrip('/')}/calendar_app/db/calendar_{calendar_id}_activemonthsdata_{year}-{month:02d}.xml"


def _months(start: date, count: int) -> list[tuple[int, int]]:
    out, y, m = [], start.year, start.month
    for _ in range(count):
        out.append((y, m))
        y, m = (y + 1, 1) if m == 12 else (y, m + 1)
    return out


def _text(event: ET.Element, tag: str) -> str:
    return (event.findtext(tag) or "").strip()


def _parse_begin(value: str) -> date | None:
    try:
        return datetime.strptime(value, "%b %d, %Y").date()
    except ValueError:
        return None


def _occurrence_dates(event: ET.Element) -> list[date]:
    listed = _text(event, "dates")
    if listed:
        out = []
        for part in listed.split(","):
            part = part.strip()
            if not part or part.endswith("+"):
                continue
            try:
                out.append(datetime.strptime(part, "%m-%d-%Y").date())
            except ValueError:
                continue
        if out:
            return out
    begin = _parse_begin(_text(event, "date_begin"))
    return [begin] if begin else []


def _duration(value: str) -> timedelta | None:
    total = timedelta()
    for amount, unit in _DURATION.findall(value or ""):
        n = int(amount)
        unit = unit.lower()
        total += timedelta(minutes=n) if unit == "min" else timedelta(days=n) if unit == "day" else timedelta(hours=n)
    return total or None


def _clean_html(value: str) -> str | None:
    if not value:
        return None
    text = BeautifulSoup(value, "html.parser").get_text(" ", strip=True)
    return re.sub(r"\s+", " ", text) or None


def parse_month(xml_text: str, *, source: str, base_url: str, default_categories: list[str], venue_name: str | None, venue_address: str | None) -> list[RawEvent]:
    """One month file -> RawEvents (every occurrence it lists, any month)."""
    root = ET.fromstring(xml_text.strip())
    page_url = f"{base_url.rstrip('/')}/calendar.php"
    out: list[RawEvent] = []
    for event in root.iter("event"):
        event_id = (event.get("id") or "").strip()
        title = _text(event, "name")
        # The app's own JS skips id <= 0 (an empty template row).
        if not event_id.isdigit() or int(event_id) <= 0 or not title:
            continue
        time_begin = _text(event, "time_begin")
        start_clock: time | None = None
        if time_begin:
            try:
                start_clock = datetime.strptime(time_begin, "%H:%M").time()
            except ValueError:
                start_clock = None
        duration = _duration(_text(event, "duration"))
        location = _text(event, "event_location") or None
        description = _clean_html(_text(event, "detail"))
        for day in _occurrence_dates(event):
            if start_clock is not None:
                start = datetime.combine(day, start_clock, tzinfo=_ET)
                end = start + duration if duration else None
                all_day = False
            else:
                start = datetime.combine(day, time.min, tzinfo=_ET)
                # A multi-day all-day run ("6days") ends after its last day.
                end = start + duration if duration and duration >= timedelta(days=1) else None
                all_day = True
            out.append(
                RawEvent(
                    source=source,
                    source_event_id=f"{event_id}:{day.isoformat()}",
                    title=title,
                    description=description,
                    start_time=start,
                    end_time=end,
                    all_day=all_day,
                    venue_name=venue_name or location,
                    venue_address=venue_address or location,
                    url=page_url,
                    default_categories=list(default_categories),
                    raw={"revize_event_id": event_id},
                )
            )
    return out


class RevizeCalendarAppSource(Source):
    def __init__(
        self,
        name: str,
        base_url: str,
        calendar_ids: list[int | str] | None = None,
        months_ahead: int = 3,
        default_categories: list[str] | None = None,
        venue_name: str | None = None,
        venue_address: str | None = None,
        timeout: float = 30.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/calendar.php"
        self.calendar_ids = list(calendar_ids or [1])
        self.months_ahead = max(1, months_ahead)
        self.default_categories = default_categories or []
        self.venue_name = venue_name
        self.venue_address = venue_address
        self.timeout = timeout
        self.partial_failures = []

    async def fetch(self) -> list[RawEvent]:
        today = datetime.now(_ET).date()
        horizon = today + timedelta(days=31 * self.months_ahead)
        seen: set[str] = set()
        out: list[RawEvent] = []
        ok = 0
        failures: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            # Month files 404 when a month is empty, so a site that left this
            # app would read as "no events" forever. The index file says it's
            # still here.
            index = await client.get(f"{self.base_url}/calendar_app/db/calendar_db_data.xml")
            index.raise_for_status()
            for calendar_id in self.calendar_ids:
                for year, month in _months(today, self.months_ahead + 1):
                    url = month_file_url(self.base_url, calendar_id, year, month)
                    resp = await client.get(url)
                    if resp.status_code == 404:
                        ok += 1  # no events that month
                        continue
                    if resp.status_code != 200:
                        failures.append(f"calendar {calendar_id} {year}-{month:02d}: HTTP {resp.status_code}")
                        continue
                    try:
                        events = parse_month(
                            resp.text, source=self.name, base_url=self.base_url,
                            default_categories=self.default_categories,
                            venue_name=self.venue_name, venue_address=self.venue_address,
                        )
                    except ET.ParseError as exc:
                        # Seen for real: a hand-edited month file with a mismatched tag.
                        failures.append(f"calendar {calendar_id} {year}-{month:02d}: bad XML ({exc})")
                        continue
                    ok += 1
                    for raw in events:
                        day = raw.start_time.date()
                        if raw.source_event_id in seen or day > horizon or (raw.end_time or raw.start_time).date() < today:
                            continue
                        seen.add(raw.source_event_id)
                        out.append(raw)
        if failures and not ok:
            # Every month failed: the site moved off this app or is down. Say so
            # instead of reporting a quiet 0.
            raise RuntimeError(f"{self.name}: no month file could be read: " + "; ".join(failures[:3]))
        self.partial_failures = failures
        return out
