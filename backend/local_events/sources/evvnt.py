"""Evvnt discovery API adapter.

Fetches events from https://discovery.evvnt.com/api/events, scoped to a
publisher_id (e.g. 8119 = 70and73.com).

Because evvnt's searchTerm is free-text and loosely scoped, the source runs one
paginated query per configured search term and then applies a geographic
bounding-box filter to drop false-positive out-of-region results. Results are
deduped on objectID across all search terms.
"""
from __future__ import annotations

import asyncio
import hashlib
import logging
import random
from datetime import datetime
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

_API_URL = "https://discovery.evvnt.com/api/events"
_UTC = ZoneInfo("UTC")
_ET = ZoneInfo("America/New_York")

_USER_AGENT = (
    "Mozilla/5.0 (compatible; BillzCalendarBot/1.0; "
    "+personal family events aggregator)"
)


def _to_utc(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=_ET)
    return dt.astimezone(_UTC)


def _pick_image(raw: dict) -> str | None:
    imgs = raw.get("images") or {}
    # API returns a dict of size-keyed image objects, not a list.
    if isinstance(imgs, list):
        imgs = imgs[0] if imgs else {}
    for key in ("featured", "hero", "list_thumb", "original"):
        node = (imgs.get(key) or {}) if isinstance(imgs, dict) else {}
        url = node.get("url")
        if url:
            return url
    return None


def _pick_prices(raw: dict) -> tuple[float | None, float | None]:
    prices = raw.get("prices") or {}
    if not isinstance(prices, dict) or not prices:
        return None, None
    amounts: list[float] = []
    for v in prices.values():
        try:
            amounts.append(float(str(v).lstrip("$").replace(",", "")))
        except ValueError:
            pass
    if not amounts:
        return None, None
    return min(amounts), max(amounts)


def _pick_url(raw: dict) -> str | None:
    return (
        raw.get("source_broadcast_url")
        or (raw.get("links") or {}).get("Tickets")
        or (raw.get("links") or {}).get("Website")
    )


def _in_bbox(raw: dict, bbox: dict) -> bool:
    geo = raw.get("_geoloc") or {}
    lat, lng = geo.get("lat"), geo.get("lng")
    if lat is None or lng is None:
        venue = raw.get("venue") or {}
        lat, lng = venue.get("latitude"), venue.get("longitude")
    if lat is None or lng is None:
        return False
    return (
        bbox["lat_min"] <= lat <= bbox["lat_max"]
        and bbox["lng_min"] <= lng <= bbox["lng_max"]
    )


def _to_raw_event(raw: dict, source_name: str, default_categories: list[str]) -> RawEvent:
    obj_id = raw["objectID"]
    venue = raw.get("venue") or {}
    price_min, price_max = _pick_prices(raw)

    start = _to_utc(raw.get("start_time"))
    end = _to_utc(raw.get("end_time")) or start
    all_day = not (raw.get("start_time") or "").count(":")

    address_parts = [p for p in (venue.get("address_1"), venue.get("address_2")) if p]
    venue_address = ", ".join(address_parts) or None
    venue_town = venue.get("town")
    if venue_address and venue_town:
        venue_address = f"{venue_address}, {venue_town}"
    elif venue_town:
        venue_address = venue_town

    category = raw.get("category_name")
    categories = list(default_categories)
    if category:
        slug = category.lower().replace(" ", "-")
        if slug not in categories:
            categories.append(slug)

    return RawEvent(
        source=source_name,
        source_event_id=f"evvnt:{obj_id}",
        title=(raw.get("title") or "").strip() or "(untitled)",
        description=raw.get("summary") or raw.get("description") or None,
        start_time=start,
        end_time=end,
        all_day=bool(all_day),
        venue_name=venue.get("name") or None,
        venue_address=venue_address,
        latitude=venue.get("latitude"),
        longitude=venue.get("longitude"),
        url=_pick_url(raw),
        image_url=_pick_image(raw),
        price_min=price_min,
        price_max=price_max,
        is_free=price_min == 0 if price_min is not None else None,
        default_categories=categories,
        raw={"objectID": obj_id, "organiser": raw.get("organiser_name")},
    )


class EvvntSource(Source):
    """Fetch events from the Evvnt discovery API for a given publisher.

    Args:
        name: Stable source identifier.
        publisher_id: Evvnt publisher account ID (e.g. 8119 for 70and73.com).
        search_terms: List of free-text search terms. One paginated query is
            issued per term; results are deduped on objectID.
        bbox: Geographic bounding box dict with lat_min, lat_max, lng_min,
            lng_max. Events outside this box are dropped.
        default_categories: Tags applied to every event from this source.
        hits_per_page: Page size (default 100, evvnt max).
        max_pages_per_term: Safety ceiling on pages per search term (default 20).
        throttle_seconds: Delay between paginated requests (default 1.5).
        timeout: HTTP request timeout in seconds (default 30).
    """

    def __init__(
        self,
        name: str,
        publisher_id: int,
        search_terms: list[str],
        bbox: dict[str, float],
        default_categories: list[str] | None = None,
        hits_per_page: int = 100,
        max_pages_per_term: int = 20,
        throttle_seconds: float = 1.5,
        timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.publisher_id = publisher_id
        self.search_terms = search_terms
        self.bbox = bbox
        self.default_categories = default_categories or []
        self.hits_per_page = hits_per_page
        self.max_pages_per_term = max_pages_per_term
        self.throttle_seconds = throttle_seconds
        self.timeout = timeout

    async def _fetch_page(self, client: httpx.AsyncClient, term: str, page: int) -> list[dict]:
        params: dict[str, Any] = {
            "hitsPerPage": self.hits_per_page,
            "multipleEventInstances": "true",
            "page": page,
            "publisher_id": self.publisher_id,
            "searchTerm": term,
        }
        max_attempts = 4
        backoff = 5.0
        for attempt in range(1, max_attempts + 1):
            try:
                resp = await client.get(
                    _API_URL,
                    params=params,
                    headers={"User-Agent": _USER_AGENT, "Accept": "application/json"},
                )
            except httpx.HTTPError as exc:
                if attempt == max_attempts:
                    raise
                delay = backoff * (3 ** (attempt - 1)) + random.uniform(0, 2)
                logger.warning(
                    "evvnt_http_error",
                    extra={"source": self.name, "term": term, "page": page, "error": str(exc), "retry_in": delay},
                )
                await asyncio.sleep(delay)
                continue

            if resp.status_code == 200:
                return resp.json().get("events") or []

            if resp.status_code in (429, 500, 502, 503, 504) and attempt < max_attempts:
                ra = resp.headers.get("Retry-After", "")
                delay = float(ra) if ra.isdigit() else backoff * (3 ** (attempt - 1)) + random.uniform(0, 2)
                logger.warning(
                    "evvnt_rate_limited",
                    extra={"source": self.name, "status": resp.status_code, "retry_in": delay},
                )
                await asyncio.sleep(delay)
                continue

            resp.raise_for_status()

        return []

    async def fetch(self) -> list[RawEvent]:
        by_id: dict[str, RawEvent] = {}

        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True) as client:
            for term in self.search_terms:
                for page in range(self.max_pages_per_term):
                    raw_events = await self._fetch_page(client, term, page)
                    if not raw_events:
                        break

                    for raw in raw_events:
                        obj_id = raw.get("objectID")
                        if not obj_id:
                            continue
                        if not _in_bbox(raw, self.bbox):
                            continue
                        key = f"evvnt:{obj_id}"
                        if key not in by_id:
                            try:
                                by_id[key] = _to_raw_event(raw, self.name, self.default_categories)
                            except Exception as exc:  # noqa: BLE001
                                logger.warning(
                                    "evvnt_entry_skipped",
                                    extra={"source": self.name, "obj_id": obj_id, "error": str(exc)},
                                )

                    if len(raw_events) < self.hits_per_page:
                        break

                    await asyncio.sleep(self.throttle_seconds)

        return sorted(by_id.values(), key=lambda e: e.start_time)
