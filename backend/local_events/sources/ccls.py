"""Camden County Library System - its own Drupal site (the "Intercept"
library-events module), not a third-party platform, so it's a public JSON:API
rather than a scrape: GET /jsonapi/node/event, filterable by
`field_location.id` and sortable by `field_date_time.value`. Voorhees has no
town library of its own; its library is a CCLS branch (M. Allan Vogelson),
which is what motivated adding the whole system rather than one branch.

Branch location ids are looked up once (GET /jsonapi/node/location) rather
than hardcoded - CCLS runs system-wide items under "Virtual"/"Off Site"/
"System Wide" pseudo-locations alongside the ~8 real branches, and those
three are excluded since they're not a place a family would drive to. A
branch closing or a new one opening changes what this returns with no code
change; only branch *names* need to be listed in job params (to build one
schoolz LocalEvent source per branch, for dedupe/logs/Test-fetch clarity),
matched case-insensitively against whatever the API currently returns.

Confirmed real: field_location.id is a *list* (an event can span more than
one branch), so an event is attributed to every configured branch it lists,
not just the first.
"""
from __future__ import annotations

import asyncio
import logging
from datetime import date, datetime, timedelta, timezone
from typing import Any

import httpx

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

_BASE = "https://events.camdencountylibrary.org"
_NON_BRANCH_LOCATIONS = {"virtual", "off site", "system wide"}
_PAGE_SIZE = 50
# Seconds slept before every branch after the first in a run. The branches are
# fetched one after another against the same Drupal server, whose slow pages
# (Voorhees ~14 s alone) timed out when queued straight behind each other.
DEFAULT_CCLS_PAUSE = 5.0
# Every attribute _to_event reads, and nothing else. Without a sparse fieldset
# Drupal returns each full node (body, metadata, ...): a Voorhees page was
# ~630 KB and took 17-43 s, so three pages blew through even a 90 s read
# timeout on prod. The same 126 events with just these fields: 3 s in total.
# Add a field here whenever _to_event starts reading another one.
_EVENT_FIELDS = "title,field_date_time,field_text_teaser,path,event_thumbnail,drupal_internal__nid"


async def list_branches(client: httpx.AsyncClient) -> dict[str, str]:
    """{branch name: location node id}, real physical branches only."""
    resp = await client.get(
        f"{_BASE}/jsonapi/node/location",
        params={"page[limit]": 50, "fields[node--location]": "title"},
        headers={"Accept": "application/json"},
    )
    resp.raise_for_status()
    out = {}
    for entry in resp.json().get("data", []):
        title = (entry.get("attributes", {}).get("title") or "").strip()
        if title and title.lower() not in _NON_BRANCH_LOCATIONS:
            out[title] = entry["id"]
    return out


class CCLSSource(Source):
    """One Camden County Library System branch's upcoming events."""

    def __init__(
        self,
        name: str,
        branch_name: str,
        default_categories: list[str] | None = None,
        days_ahead: int = 90,
        max_pages: int = 20,
        timeout: float = 30.0,
        pause_before: float = 0.0,
    ) -> None:
        self.name = name
        self.branch_name = branch_name
        self.pause_before = pause_before
        self.default_categories = list(default_categories or []) + ["library"]
        self.days_ahead = days_ahead
        self.max_pages = max_pages
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        if self.pause_before:
            await asyncio.sleep(self.pause_before)
        async with httpx.AsyncClient(timeout=self.timeout) as client:
            branches = await list_branches(client)
            location_id = next((v for k, v in branches.items() if k.lower() == self.branch_name.lower()), None)
            if not location_id:
                logger.warning(
                    "ccls_branch_not_found",
                    extra={"source": self.name, "branch_name": self.branch_name, "known_branches": sorted(branches)},
                )
                return []

            today = date.today()
            window_end = today + timedelta(days=self.days_ahead)
            url: str | None = f"{_BASE}/jsonapi/node/event"
            params: dict[str, Any] | None = {
                "filter[loc][condition][path]": "field_location.id",
                "filter[loc][condition][value]": location_id,
                "filter[after][condition][path]": "field_date_time.end_value",
                "filter[after][condition][operator]": ">=",
                "filter[after][condition][value]": today.isoformat() + "T00:00:00",
                "filter[before][condition][path]": "field_date_time.value",
                "filter[before][condition][operator]": "<=",
                "filter[before][condition][value]": window_end.isoformat() + "T23:59:59",
                "sort": "field_date_time.value",
                "page[limit]": _PAGE_SIZE,
                "fields[node--event]": _EVENT_FIELDS,
            }

            out: list[RawEvent] = []
            for _ in range(self.max_pages):
                if not url:
                    break
                resp = await client.get(url, params=params, headers={"Accept": "application/json"})
                resp.raise_for_status()
                payload = resp.json()
                params = None  # only the first request needs the filter querystring; `links.next` already has it baked in

                for entry in payload.get("data", []):
                    event = self._to_event(entry)
                    if event:
                        out.append(event)

                url = (payload.get("links", {}).get("next") or {}).get("href")

            return out

    def _to_event(self, entry: dict) -> RawEvent | None:
        attrs = entry.get("attributes") or {}
        date_time = attrs.get("field_date_time") or {}
        start_raw = date_time.get("value")
        if not start_raw:
            return None
        try:
            start = datetime.fromisoformat(start_raw)
        except ValueError:
            return None
        end = None
        if end_raw := date_time.get("end_value"):
            try:
                end = datetime.fromisoformat(end_raw)
            except ValueError:
                end = None

        title = (attrs.get("title") or "").strip() or "(untitled)"
        teaser = ((attrs.get("field_text_teaser") or {}).get("value") or "").strip()
        alias = (attrs.get("path") or {}).get("alias")
        thumbnail = attrs.get("event_thumbnail")

        return RawEvent(
            source=self.name,
            source_event_id=entry.get("id") or f"hash:{title}|{start.isoformat()}",
            title=title,
            description=teaser or None,
            start_time=start,
            end_time=end,
            all_day=False,
            venue_name=f"Camden County Library - {self.branch_name}",
            url=(_BASE + alias) if alias else None,
            image_url=thumbnail,
            default_categories=list(self.default_categories),
            raw={"nid": attrs.get("drupal_internal__nid")},
        )
