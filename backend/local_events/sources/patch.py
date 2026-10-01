"""Patch.com town calendars (patch.com/new-jersey/<slug>/calendar).

Patch is a Next.js site that server-renders a region's whole calendar into
`__NEXT_DATA__` (pageProps.mainContent.allEvents, grouped by day), so plain
httpx is enough - no scraper, no login.

Why this is a *list of regions* in one source, not one source per town:
  * Patch only runs a handful of real newsrooms near us (cherryhill,
    collingswood, haddon, moorestown, gloucestertownship) plus thin `-nj`
    town pages (marlton-nj, medford-nj, ...) that show only the few events
    submitted to them. Every region repeats its neighbours' events and the
    same paid "promoted" placements, under the same event id. One source
    dedupes by id across regions; separate sources would insert each twice.
  * Most other `-nj` pages (audubon-nj, somerdale-nj, ...) are placeholders
    that carry a different, thinner event shape ("patchAmFreeEvent": no link,
    no real start instant). Those rows have no `displayDate` and are skipped.

`fetch_via` is "direct" (plain httpx, the default) or "scraper" (the shared
scraper chain with the residential Pi first, then the droplet, then
schoolz's own scraper).

Promoted placements come from anywhere in the state (a Paramus webinar, a
Wildwood car show), so `center` + `max_miles` on the event's coordinates
drop them. Plenty of genuinely local events carry a city but 0,0 coordinates,
so an event with no coordinates is kept when it names a city or street and
dropped when it names neither - which is what removes the online webinars.

Example job-params entry:

    {
      "name": "patch",
      "regions": ["cherryhill", "collingswood", "haddon", "moorestown"],
      "center": [39.85, -74.98],
      "max_miles": 15,
      "fetch_via": "scraper",
      "default_categories": ["patch"]
    }
"""
from __future__ import annotations

import asyncio
import html as html_lib
import json
import math
import re
from datetime import datetime
from typing import Any

import httpx

from .base import RawEvent, Source
from .scraper import fetch_rendered_html

_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_NEXT_DATA_RE = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.S)
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_ORIGIN = "https://patch.com"
# Politeness between region fetches; Patch's robots.txt blocks several crawlers by name.
_PAUSE_SECONDS = 2.0


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def _miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _coords(address: dict) -> tuple[float, float] | None:
    try:
        lat, lng = float(address.get("latitude") or 0), float(address.get("longitude") or 0)
    except (TypeError, ValueError):
        return None
    return (lat, lng) if lat and lng else None


def region_events(page_html: str) -> list[dict]:
    """Every full-shape event on a region page, deduped by id (a multi-day
    event appears under each of its days)."""
    match = _NEXT_DATA_RE.search(page_html)
    if not match:
        raise ValueError("no __NEXT_DATA__ on the page - not a Patch calendar any more?")
    main = json.loads(match.group(1)).get("props", {}).get("pageProps", {}).get("mainContent")
    if not isinstance(main, dict) or not isinstance(main.get("allEvents"), dict):
        raise ValueError("no mainContent.allEvents in __NEXT_DATA__")
    found: dict[str, dict] = {}
    for day in main["allEvents"].values():
        for ev in day or []:
            if isinstance(ev, dict) and ev.get("id") and ev.get("displayDate") and ev.get("itemAlias"):
                found.setdefault(str(ev["id"]), ev)
    return list(found.values())


def to_raw(
    ev: dict,
    source: str,
    *,
    center: tuple[float, float] | None = None,
    max_miles: float | None = None,
    default_categories: list[str] | None = None,
) -> RawEvent | None:
    start = _dt(ev.get("displayDate"))
    title = _text(ev.get("title"))
    if start is None or not title:
        return None
    address = ev.get("address") or {}
    coords = _coords(address)
    if max_miles and center:
        if coords is not None:
            if _miles(center, coords) > max_miles:
                return None
        elif not (address.get("city") or address.get("streetAddress")):
            return None  # online webinar: no coordinates and no place at all
    street_parts = [address.get("streetAddress"), address.get("city"), address.get("region"), address.get("postalCode")]
    description = _text(ev.get("summary")) or _text(ev.get("body")) or None
    return RawEvent(
        source=source,
        source_event_id=str(ev["id"]),
        title=title,
        description=description,
        start_time=start,
        venue_name=(address.get("name") or "").strip() or None,
        venue_address=", ".join(p for p in street_parts if p) or None,
        latitude=coords[0] if coords else None,
        longitude=coords[1] if coords else None,
        url=_ORIGIN + ev["itemAlias"],
        image_url=ev.get("imageThumbnail"),
        # "paid" on Patch is a listing tier, not a ticket price, so only free is a claim.
        is_free=True if ev.get("eventType") == "free" else None,
        default_categories=list(default_categories or []),
        raw={"patch_id": ev["id"], "promoted": bool(ev.get("promoted")), "event_site_url": ev.get("eventSiteUrl")},
    )


def parse_region(
    page_html: str,
    source: str,
    *,
    center: tuple[float, float] | None = None,
    max_miles: float | None = None,
    default_categories: list[str] | None = None,
) -> list[RawEvent]:
    out = (
        to_raw(ev, source, center=center, max_miles=max_miles, default_categories=default_categories)
        for ev in region_events(page_html)
    )
    return [e for e in out if e is not None]


class PatchSource(Source):
    def __init__(
        self,
        name: str,
        regions: list[str],
        *,
        center: list[float] | None = None,
        max_miles: float | None = None,
        default_categories: list[str] | None = None,
        fetch_via: str = "direct",
        timeout: float = 30.0,
    ) -> None:
        if fetch_via not in ("direct", "scraper"):
            raise ValueError("fetch_via must be 'direct' or 'scraper'")
        self.fetch_via = fetch_via
        self.name = name
        self.regions = regions
        self.center = (float(center[0]), float(center[1])) if center and len(center) == 2 else None
        self.max_miles = float(max_miles) if max_miles else None
        self.default_categories = default_categories or []
        self.timeout = timeout
        self.partial_failures: list[str] = []

    async def _get(self, client: httpx.AsyncClient, url: str) -> str:
        if self.fetch_via == "scraper":
            # Residential Pi first, then the droplet, then schoolz's own scraper.
            html, _ = await fetch_rendered_html(url, prefer_residential=True, timeout_ms=30_000)
            return html
        resp = await client.get(url)
        resp.raise_for_status()
        return resp.text

    async def fetch(self) -> list[RawEvent]:
        self.partial_failures = []
        events: dict[str, RawEvent] = {}
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            for i, region in enumerate(self.regions):
                if i:
                    await asyncio.sleep(_PAUSE_SECONDS)
                try:
                    parsed = parse_region(
                        await self._get(client, f"{_ORIGIN}/new-jersey/{region}/calendar"),
                        self.name,
                        center=self.center,
                        max_miles=self.max_miles,
                        default_categories=self.default_categories,
                    )
                except (httpx.HTTPError, ValueError, RuntimeError) as exc:
                    self.partial_failures.append(f"{region}: {exc}")
                    continue
                for ev in parsed:
                    events.setdefault(ev.source_event_id, ev)
        if self.regions and len(self.partial_failures) == len(self.regions):
            raise RuntimeError("every Patch region failed: " + "; ".join(self.partial_failures))
        return list(events.values())
