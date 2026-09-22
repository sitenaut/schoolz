"""Google Calendar API source adapter.

Fetches events from one or more public Google Calendar IDs using the
Calendar v3 REST API with an API key (no OAuth required for public calendars).

Handles:
- Timed events (start.dateTime / end.dateTime)
- All-day events (start.date / end.date)
- Cancelled events (status == "cancelled" → skipped)
- Multiple calendar IDs (results merged and deduplicated by source_event_id)
- Dynamic timeMin / timeMax window

Example job-params entry:

    {
      "name": "phila_gov",
      "calendar_ids": [
        "nu2baij5smvfl510s9jnuk2kd0@group.calendar.google.com"
      ],
      "api_key": "AIzaSy...",
      "default_categories": ["philadelphia", "municipal"],
      "months_ahead": 6
    }
"""
from __future__ import annotations

import logging
from datetime import date, datetime, time, timezone, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

_GCAL_BASE = "https://www.googleapis.com/calendar/v3/calendars"
_ET = ZoneInfo("America/New_York")


def _parse_gcal_dt(start: dict) -> tuple[datetime | None, bool]:
    """Return (datetime, is_all_day) from a Google Calendar start/end block."""
    if not isinstance(start, dict):
        return None, False
    if dt_str := start.get("dateTime"):
        try:
            dt = datetime.fromisoformat(dt_str)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=_ET)
            return dt, False
        except ValueError:
            return None, False
    if d_str := start.get("date"):
        try:
            d = date.fromisoformat(d_str)
            return datetime.combine(d, time.min, tzinfo=_ET), True
        except ValueError:
            return None, False
    return None, False


class GoogleCalendarSource(Source):
    def __init__(
        self,
        name: str,
        calendar_ids: list[str],
        api_key: str,
        *,
        default_categories: list[str] | None = None,
        months_ahead: int = 6,
        referer: str | None = None,
        timeout: float = 30.0,
    ):
        self.name = name
        self.calendar_ids = list(calendar_ids)
        self.api_key = api_key
        self.default_categories = default_categories or []
        self.months_ahead = max(1, int(months_ahead))
        self.referer = referer
        self.timeout = timeout

    def _build_url(self, calendar_id: str) -> str:
        now = datetime.now(tz=_ET)
        time_min = now.isoformat()
        time_max = (now + timedelta(days=30 * self.months_ahead)).isoformat()
        from urllib.parse import quote, urlencode
        params = urlencode({
            "key": self.api_key,
            "timeMin": time_min,
            "timeMax": time_max,
            "singleEvents": "true",
            "orderBy": "startTime",
            "maxResults": 250,
        })
        return f"{_GCAL_BASE}/{quote(calendar_id, safe='')}/events/?{params}"

    async def _fetch_calendar(self, client: httpx.AsyncClient, calendar_id: str) -> list[RawEvent]:
        url = self._build_url(calendar_id)
        headers: dict[str, str] = {"User-Agent": "schoolz-local-events/1.0"}
        if self.referer:
            headers["Referer"] = self.referer

        resp = await client.get(url, headers=headers)
        if not resp.is_success:
            raise RuntimeError(
                f"Google Calendar API returned HTTP {resp.status_code} for calendar "
                f"{calendar_id!r}: {resp.text[:200]}"
            )
        data = resp.json()
        cal_name = data.get("summary") or calendar_id

        items = data.get("items") or []
        out: list[RawEvent] = []
        for item in items:
            if not isinstance(item, dict):
                continue
            if item.get("status") == "cancelled":
                continue
            try:
                start_dt, all_day = _parse_gcal_dt(item.get("start") or {})
                if start_dt is None:
                    continue
                end_dt, _ = _parse_gcal_dt(item.get("end") or {})
                title = (item.get("summary") or "").strip() or "(untitled)"
                out.append(RawEvent(
                    source=self.name,
                    source_event_id=item["id"],
                    title=title,
                    description=(item.get("description") or "").strip() or None,
                    start_time=start_dt,
                    end_time=end_dt,
                    all_day=all_day,
                    venue_address=(item.get("location") or "").strip() or None,
                    url=item.get("htmlLink"),
                    default_categories=list(self.default_categories),
                    raw={"calendar_id": calendar_id, "calendar_name": cal_name, "gcal_status": item.get("status")},
                ))
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "gcal_item_skipped",
                    extra={"source": self.name, "calendar_id": calendar_id, "error": str(exc)},
                )
                continue
        return out

    async def fetch(self) -> list[RawEvent]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            all_events: list[RawEvent] = []
            seen_ids: set[str] = set()
            for cal_id in self.calendar_ids:
                for event in await self._fetch_calendar(client, cal_id):
                    if event.source_event_id not in seen_ids:
                        seen_ids.add(event.source_event_id)
                        all_events.append(event)
        return all_events
