"""Incident IQ public calendars - Pine Hill's "Facility Events Calendars"
pages (one per school, plus district-wide and field trips) embed an Incident
IQ "public calendar" widget that loads after the page does (2-3 seconds, so
a fetch that doesn't wait sees an empty body).

The widget POSTs `{"ViewId": "<guid>", "Upcoming": true, ...}` to
`https://<tenant>.incidentiq.com/api/event/events`, anonymously, and gets back
a small HTML page whose hidden `#eventData` input holds the events as JSON. No
browser needed; the ViewId is read off the page's own network call once, like
Finalsite's `feed_id`.

A feed entry is stored as `https://<tenant>.incidentiq.com/api/event/events?ViewId=<guid>`
(a key, not a GET endpoint) so it rides in `District.ics_feeds` beside real
ICS feeds; `district_calendar.fetch_district_calendar` routes it here.
Events have no id and carry room bookings, so the uid hashes title + start + rooms.
"""

import hashlib
import html
import json
import re
from datetime import datetime, time
from urllib.parse import parse_qs, urlparse
from zoneinfo import ZoneInfo

import httpx

_ET = ZoneInfo("America/New_York")
_DATA_RE = re.compile(r'id="eventData"\s+value="([^"]*)"')


def is_incidentiq_feed(url: str) -> bool:
    parsed = urlparse(url)
    return (parsed.hostname or "").lower().endswith(".incidentiq.com") and "viewid" in {k.lower() for k in parse_qs(parsed.query)}


def parse_events(page_html: str) -> list[dict]:
    match = _DATA_RE.search(page_html)
    if not match:
        return []
    try:
        raw = json.loads(html.unescape(match.group(1)))
    except ValueError:
        return []
    out = []
    for event in raw if isinstance(raw, list) else []:
        try:
            start = datetime.fromisoformat(event["start"]).replace(tzinfo=_ET)
        except (KeyError, TypeError, ValueError):
            continue
        end = None
        if event.get("end"):
            try:
                end = datetime.fromisoformat(event["end"]).replace(tzinfo=_ET)
            except ValueError:
                end = None
        title = (event.get("title") or "").strip() or "(untitled)"
        rooms = sorted(
            {
                f'{r.get("LocationName") or ""} - {r.get("NameFormatted") or r.get("Name") or ""}'.strip(" -")
                for r in event.get("locationRooms") or []
            }
            - {""}
        )
        digest = hashlib.sha1(f"{title}|{start.isoformat()}|{'|'.join(rooms)}".encode("utf-8")).hexdigest()
        out.append(
            {
                "external_uid": f"iiq:{digest[:24]}",
                "title": title[:300],
                "description": ("Location: " + "; ".join(rooms)) if rooms else None,
                "start_date": start,
                "end_date": end,
                "is_all_day": start.timetz().replace(tzinfo=None) == time.min and (end is None or end.timetz().replace(tzinfo=None) == time.min),
            }
        )
    return out


async def fetch_events(feed_url: str, timeout: float = 30.0) -> list[dict]:
    """Same shape as district_calendar.fetch_district_calendar."""
    parsed = urlparse(feed_url)
    view_id = next(v[0] for k, v in parse_qs(parsed.query).items() if k.lower() == "viewid")
    origin = f"{parsed.scheme}://{parsed.hostname}"
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
        resp = await client.post(
            f"{origin}/api/event/events",
            json={"FilterByProduct": True, "ViewId": view_id, "Upcoming": True, "Origin": origin},
            headers={"User-Agent": "Mozilla/5.0 (schoolz district calendar)"},
        )
        resp.raise_for_status()
    return parse_events(resp.text)
