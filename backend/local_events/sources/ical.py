"""Generic iCal/ICS adapter.

Fetches an .ics URL over HTTP and yields RawEvent rows for each VEVENT. Recurring
events are expanded only via their explicit DTSTART (no RRULE expansion yet) —
most municipal/library calendars emit one VEVENT per occurrence, so this is fine
for tier-2 sources. RRULE expansion can be added later via `icalendar.recurrence`.
"""
from __future__ import annotations

import hashlib
import logging
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

from .base import RawEvent, Source
from .scraper import fetch_raw_via_scraper

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _as_datetime(value) -> datetime | None:
    """Coerce iCal date/datetime into a tz-aware datetime.

    A bare iCal DATE (all-day event, e.g. "first day of school") has no
    timezone of its own — it's a floating calendar date. Anchoring it to UTC
    midnight is wrong: converted back to any US timezone for display/filtering,
    that lands on the *previous* local day (e.g. 2026-09-02T00:00Z reads as
    2026-09-01 20:00 in ET), which is exactly the off-by-one bug this fixes.
    Anchor to ET midnight instead, matching json_api.py's same-purpose fix.
    Timed (datetime) values are untouched other than assuming ET if the feed
    omitted a timezone.
    """
    if value is None:
        return None
    if isinstance(value, datetime):
        return value if value.tzinfo else value.replace(tzinfo=_ET)
    if isinstance(value, date):
        return datetime.combine(value, time.min, tzinfo=_ET)
    return None


def _stable_id(uid: str | None, title: str, dt: datetime) -> str:
    if uid:
        return uid
    digest = hashlib.sha1(f"{title}|{dt.isoformat()}".encode("utf-8")).hexdigest()
    return f"hash:{digest[:24]}"


class ICalSource(Source):
    def __init__(
        self,
        name: str,
        url: str,
        default_categories: list[str] | None = None,
        timeout: float = 30.0,
        via_scraper: bool = False,
    ):
        self.name = name
        self.url = url
        self.default_categories = default_categories or []
        self.timeout = timeout
        self.via_scraper = via_scraper

    async def fetch(self) -> list[RawEvent]:
        if self.via_scraper:
            # Route through Playwright via /fetch-raw to bypass WAF/Cloudflare.
            # Uses expect_download() so ICS file downloads are captured as raw
            # bytes rather than crashing the Playwright worker.
            raw_text = await fetch_raw_via_scraper(self.url, timeout=90.0)
            body = raw_text.encode("utf-8")
        else:
            async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
                resp = await client.get(self.url, headers={"User-Agent": "schoolz-local-events/1.0"})
                resp.raise_for_status()
                body = resp.content

        try:
            cal = Calendar.from_ical(body)
        except Exception as exc:  # noqa: BLE001
            logger.warning("ical_parse_failed", extra={"source": self.name, "error": str(exc)})
            return []

        out: list[RawEvent] = []
        for component in cal.walk("VEVENT"):
            try:
                dtstart = component.get("DTSTART")
                if dtstart is None:
                    continue
                start = _as_datetime(dtstart.dt)
                if start is None:
                    continue
                dtend = component.get("DTEND")
                end = _as_datetime(dtend.dt) if dtend is not None else None
                all_day = isinstance(dtstart.dt, date) and not isinstance(dtstart.dt, datetime)

                title = str(component.get("SUMMARY") or "").strip() or "(untitled)"
                description = str(component.get("DESCRIPTION") or "").strip() or None
                location = str(component.get("LOCATION") or "").strip() or None
                url = component.get("URL")
                url_str = str(url) if url else None
                uid = str(component.get("UID")) if component.get("UID") else None

                out.append(
                    RawEvent(
                        source=self.name,
                        source_event_id=_stable_id(uid, title, start),
                        title=title,
                        description=description,
                        start_time=start,
                        end_time=end,
                        all_day=all_day,
                        venue_name=location,
                        venue_address=location,
                        url=url_str,
                        default_categories=list(self.default_categories),
                        raw={"uid": uid},
                    )
                )
            except Exception as exc:  # noqa: BLE001
                logger.warning("ical_vevent_skipped", extra={"source": self.name, "error": str(exc)})
                continue
        return out
