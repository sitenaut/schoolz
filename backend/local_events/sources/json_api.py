"""Generic JSON API adapter for event calendars.

Fetches a URL that returns a JSON payload, navigates to the events array via a
configurable dot-path, and maps JSON fields to RawEvent fields by name. An
optional `parser` key selects site-specific post-processing logic.

Supported parsers:
  "dpcalendar" — DPCalendar (Joomla component used by many NJ townships).
                 Extracts calendar-category name and plain-text description
                 from the HTML tooltip in the `description` field.
"""
from __future__ import annotations

import hashlib
import logging
import re
from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import httpx
from bs4 import BeautifulSoup

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

_TZ_ET = None  # resolved lazily to avoid import-time zoneinfo errors


def _et() -> Any:
    global _TZ_ET
    if _TZ_ET is None:
        try:
            from zoneinfo import ZoneInfo

            _TZ_ET = ZoneInfo("America/New_York")
        except Exception:  # noqa: BLE001
            _TZ_ET = timezone.utc
    return _TZ_ET


def _parse_dt(value: str | None, all_day: bool) -> datetime | None:
    if not value:
        return None
    try:
        dt = datetime.fromisoformat(value)
    except ValueError:
        return None
    if dt.tzinfo is None:
        if all_day:
            # Date-only all-day events: treat as midnight ET.
            if len(value) == 10:  # "YYYY-MM-DD"
                d = date.fromisoformat(value)
                dt = datetime.combine(d, time.min, tzinfo=_et())
            else:
                dt = dt.replace(tzinfo=_et())
        else:
            dt = dt.replace(tzinfo=_et())
    return dt


def _dig(obj: Any, path: str) -> Any:
    """Navigate a nested dict using dot-notation (e.g. 'data.events')."""
    for key in path.split("."):
        if not isinstance(obj, dict):
            return None
        obj = obj.get(key)
    return obj


def _stable_id(raw_id: Any, title: str, start: datetime) -> str:
    if raw_id is not None:
        return str(raw_id)
    digest = hashlib.sha1(f"{title}|{start.isoformat()}".encode()).hexdigest()
    return f"hash:{digest[:24]}"


# ---------------------------------------------------------------------------
# Site-specific parsers
# ---------------------------------------------------------------------------


def _parse_dpcalendar(event: dict, raw_event: RawEvent) -> RawEvent:
    """Post-process a DPCalendar JSON event.

    The description field is an HTML tooltip blob.  Extract:
    - dp-event-tooltip__calendar text  →  extra category tag
    - dp-event-tooltip__description text  →  clean description
    - dp-event-tooltip_canceled presence  →  prefix title with [Cancelled]
    """
    html = event.get("description") or ""
    if not html:
        return raw_event

    soup = BeautifulSoup(html, "html.parser")

    # Calendar name → extra category (strip surrounding brackets).
    cal_el = soup.find(class_="dp-event-tooltip__calendar")
    extra_categories: list[str] = []
    if cal_el:
        cal_name = cal_el.get_text(strip=True).strip("[]").strip().lower()
        if cal_name and cal_name not in ("main calendar", "event"):
            # Normalise: "Mayor & Council" → "mayor-council"
            slug = re.sub(r"[^a-z0-9]+", "-", cal_name).strip("-")
            extra_categories = [slug]

    # Description text.
    desc_el = soup.find(class_="dp-event-tooltip__description")
    desc_text = desc_el.get_text(" ", strip=True) if desc_el else None
    # Trim trailing ellipsis artefacts.
    if desc_text:
        desc_text = re.sub(r"\s*\.\.\.$", "…", desc_text).strip() or None

    # Cancelled detection.
    cancelled = bool(
        soup.find(class_=re.compile(r"dp-event-tooltip_canceled"))
        or re.match(r"^\[cancelled\]", raw_event.title, re.IGNORECASE)
    )
    title = raw_event.title
    if cancelled and not title.lower().startswith("[cancelled]"):
        title = f"[Cancelled] {title}"

    return raw_event.model_copy(
        update={
            "title": title,
            "description": desc_text,
            "default_categories": list(raw_event.default_categories) + extra_categories,
        }
    )


DPCALENDAR_WINDOW_DAYS = 90

_PARSERS: dict[str, Any] = {
    "dpcalendar": _parse_dpcalendar,
}


# ---------------------------------------------------------------------------
# Source adapter
# ---------------------------------------------------------------------------


class JsonApiSource(Source):
    """Fetch a JSON event feed and map fields to RawEvent.

    Args:
        name: Stable source identifier (used for dedupe and logs).
        url: JSON endpoint URL.
        base_url: Prepended to relative URLs in the url_field (e.g. "https://evesham-nj.org").
        data_path: Dot-path to the events array in the response (default "data.events").
        id_field: JSON key for the stable event ID (default "id").
        title_field: JSON key for the event title (default "title").
        start_field: JSON key for start datetime string (default "start").
        end_field: JSON key for end datetime string (default "end").
        all_day_field: JSON key for the all-day boolean (default "allDay").
        url_field: JSON key for the event URL (default "url").
        description_field: JSON key for description HTML/text (default "description").
        image_field: JSON key for image URL (optional).
        parser: Named site-specific post-processor (e.g. "dpcalendar").
        default_categories: Tags applied to every event from this source.
        timeout: HTTP request timeout in seconds.
    """

    def __init__(
        self,
        name: str,
        url: str,
        base_url: str | None = None,
        data_path: str = "data.events",
        id_field: str = "id",
        title_field: str = "title",
        start_field: str = "start",
        end_field: str = "end",
        all_day_field: str = "allDay",
        url_field: str = "url",
        description_field: str = "description",
        image_field: str | None = None,
        parser: str | None = None,
        default_categories: list[str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.url = url
        self.base_url = (base_url or "").rstrip("/")
        self.data_path = data_path
        self.id_field = id_field
        self.title_field = title_field
        self.start_field = start_field
        self.end_field = end_field
        self.all_day_field = all_day_field
        self.url_field = url_field
        self.description_field = description_field
        self.image_field = image_field
        self.parser = parser
        self.parser_fn = _PARSERS.get(parser) if parser else None
        if parser and self.parser_fn is None:
            logger.warning("json_api_unknown_parser", extra={"source": name, "parser": parser})
        self.default_categories = default_categories or []
        self.timeout = timeout

    def request_url(self, today: date | None = None) -> str:
        """DPCalendar's raw events feed returns an empty list unless it's
        given a date range (confirmed on evesham-nj.org, which billz's own
        default config hits with none - it has always come back with 0
        events). A fixed range in the configured URL would go stale, so one
        is added per fetch unless the URL already sets its own."""
        if self.parser != "dpcalendar" or "date-start=" in self.url:
            return self.url
        start = today or date.today()
        sep = "&" if "?" in self.url else "?"
        return f"{self.url}{sep}date-start={start.isoformat()}&date-end={(start + timedelta(days=DPCALENDAR_WINDOW_DAYS)).isoformat()}"

    async def fetch(self) -> list[RawEvent]:
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            resp = await client.get(self.request_url(), headers={"User-Agent": "schoolz-local-events/1.0"})
            resp.raise_for_status()
            data = resp.json()

        events_raw = _dig(data, self.data_path)
        if not isinstance(events_raw, list):
            logger.warning(
                "json_api_no_events_array",
                extra={"source": self.name, "data_path": self.data_path},
            )
            return []

        out: list[RawEvent] = []
        for entry in events_raw:
            if not isinstance(entry, dict):
                continue
            try:
                all_day = bool(entry.get(self.all_day_field, False))
                start = _parse_dt(entry.get(self.start_field), all_day)
                if start is None:
                    continue
                end = _parse_dt(entry.get(self.end_field), all_day)
                title = str(entry.get(self.title_field) or "").strip() or "(untitled)"
                raw_id = entry.get(self.id_field)
                source_event_id = _stable_id(raw_id, title, start)

                raw_url = entry.get(self.url_field) or ""
                if raw_url and raw_url.startswith("/") and self.base_url:
                    event_url = self.base_url + raw_url
                elif raw_url:
                    event_url = raw_url
                else:
                    event_url = None

                image_url = entry.get(self.image_field) if self.image_field else None

                raw_event = RawEvent(
                    source=self.name,
                    source_event_id=source_event_id,
                    title=title,
                    description=str(entry.get(self.description_field) or "").strip() or None,
                    start_time=start,
                    end_time=end,
                    all_day=all_day,
                    url=event_url,
                    image_url=str(image_url) if image_url else None,
                    default_categories=list(self.default_categories),
                    raw={"source_id": raw_id},
                )

                if self.parser_fn is not None:
                    raw_event = self.parser_fn(entry, raw_event)

                out.append(raw_event)
            except Exception as exc:  # noqa: BLE001
                logger.warning(
                    "json_api_entry_skipped",
                    extra={"source": self.name, "error": str(exc)},
                )
                continue

        return out
