"""The Events Calendar (Modern Tribe / StellarWP) - the most common WordPress
events plugin - via its public REST API at /wp-json/tribe/events/v1/events.
Structured JSON with venue, coordinates, cost and categories, so no scraper
and no HTML parsing beyond stripping the description.

Two things the API won't tell you honestly:
  - A site's own time zone setting can be wrong. downtownhaddonfield.com
    reports "UTC+0" and utc_start_date == start_date, yet its 11:00 event
    really starts at 11 AM Eastern. `start_date` is always the wall-clock
    time the site's editors typed, so it's read as America/New_York and the
    *_utc fields are ignored.
  - Regional hubs are huge. visitsouthjersey.com has ~3,900 upcoming events
    stretching past a year and reaching Cape May, ~80 miles away. Hence
    `days_ahead` (sent as end_date, so the API does the trimming) and an
    optional `max_miles` radius on the venue's coordinates. About 40% of
    venues have no coordinates but do have a zip; for those,
    `nearby_zip_prefixes` stands in for the radius (080/081 is the Cherry
    Hill/Camden/Burlington side; 082 Cape May, 083 Vineland, 084 Atlantic
    City are not; 190/191 is Philadelphia). No location at all: kept.

Example job-params entry:

    {
      "name": "visit_south_jersey",
      "base_url": "https://visitsouthjersey.com",
      "days_ahead": 60,
      "max_miles": 50,
      "center": [39.9346, -75.0307],
      "nearby_zip_prefixes": ["080", "081", "190", "191"],
      "default_categories": []
    }
"""
from __future__ import annotations

import html
import json
import math
import re
from datetime import date, datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

ET = ZoneInfo("America/New_York")
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")
_MONEY_RE = re.compile(r"\d+(?:\.\d+)?")
_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")

CHERRY_HILL = (39.9346, -75.0307)
PER_PAGE = 50
DEFAULT_DAYS_AHEAD = 60
DEFAULT_MAX_PAGES = 40
SCRAPER_ATTEMPTS = 4
DEFAULT_NEARBY_ZIP_PREFIXES = ("080", "081", "190", "191")

# Site category names (lowercased, entities unescaped) -> this app's
# vocabulary. Anything unmapped is dropped rather than slugified: each site
# invents its own taxonomy, and passing it through would flood the /local
# category menu with one-off chips. The normalizer's keyword rules still
# tag from the title/description.
_CATEGORY_MAP = {
    "family fun": ["family"],
    "adventure & family fun": ["family", "outdoor"],
    "family friendly": ["family"],
    "kids": ["kids", "family"],
    "arts and entertainment": ["arts", "entertainment"],
    "art": ["arts"],
    "live music": ["live-music", "music"],
    "music": ["music"],
    "great outdoors": ["outdoor"],
    "history & museums": ["arts"],
    "breweries and distilleries": ["food-&-drink"],
    "south jersey wine region": ["food-&-drink"],
    "dining and entertainment": ["food-&-drink", "entertainment"],
    "food truck": ["food-&-drink"],
    "food & drink": ["food-&-drink"],
    "downtowns and shopping": ["shopping"],
    "shopping": ["shopping"],
    "community event": ["community"],
    "festivals": ["outdoor"],
    "classes": ["classes-&-lessons"],
    "workshops": ["classes-&-lessons"],
}


def _text(value: Any) -> str | None:
    if not value:
        return None
    cleaned = _WS_RE.sub(" ", _TAG_RE.sub(" ", html.unescape(str(value)))).strip()
    return cleaned or None


def _local_dt(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
    except ValueError:
        return None


def _miles(a: tuple[float, float], b: tuple[float, float]) -> float:
    lat1, lng1, lat2, lng2 = map(math.radians, (*a, *b))
    h = math.sin((lat2 - lat1) / 2) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin((lng2 - lng1) / 2) ** 2
    return 3958.8 * 2 * math.asin(math.sqrt(h))


def _price(event: dict) -> tuple[float | None, float | None, bool | None]:
    cost = _text(event.get("cost")) or ""
    if not cost:
        return None, None, None
    if "free" in cost.lower():
        return 0.0, 0.0, True
    values = [float(v) for v in _MONEY_RE.findall(cost.replace(",", ""))]
    if not values:
        return None, None, None
    return min(values), max(values), min(values) == 0


class TribeEventsSource(Source):
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        default_categories: list[str] | None = None,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        max_miles: float | None = None,
        center: tuple[float, float] | list[float] | None = None,
        nearby_zip_prefixes: list[str] | tuple[str, ...] | None = None,
        max_pages: int = DEFAULT_MAX_PAGES,
        timeout: float = 30.0,
        via_scraper: bool = False,
        venue_name: str | None = None,
        venue_address: str | None = None,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/wp-json/tribe/events/v1/events"
        self.default_categories = default_categories or []
        self.days_ahead = max(1, int(days_ahead))
        self.max_miles = float(max_miles) if max_miles else None
        self.center = tuple(center) if center else CHERRY_HILL
        self.nearby_zip_prefixes = tuple(nearby_zip_prefixes) if nearby_zip_prefixes is not None else DEFAULT_NEARBY_ZIP_PREFIXES
        self.max_pages = max(1, int(max_pages))
        self.timeout = timeout
        self.skipped_far = 0
        # Cloudflare-fronted sites 403 plain HTTP (runnemedepubliclibrary.org); the
        # scraper's browser gets the JSON. The home-IP scraper is blocked there too,
        # so it isn't preferred.
        self.via_scraper = via_scraper
        # Fallback for events that carry no venue of their own - a library's
        # events are at the library (haddonheightslibrary.com sets none).
        self.venue_name = venue_name
        self.venue_address = venue_address

    async def _get_json(self, client: httpx.AsyncClient, url: str, params: dict[str, Any] | None) -> tuple[int, Any]:
        if not self.via_scraper:
            resp = await client.get(url, params=params)
            if resp.status_code == 404:
                return 404, None
            resp.raise_for_status()
            return resp.status_code, resp.json()
        from .scraper import fetch_rendered_html

        full = str(httpx.URL(url).copy_merge_params(params or {}))
        # Cloudflare lets some of the scraper's requests through and 403s others
        # (an HTML "403 - Forbidden" page, not a challenge page), so try a few times.
        for _attempt in range(SCRAPER_ATTEMPTS):
            page, _ = await fetch_rendered_html(full, timeout_ms=int(self.timeout * 1000))
            # Chromium shows a JSON response inside <pre>; the REST API's 404 is JSON too.
            body = html.unescape(_TAG_RE.sub("", page)).strip()
            if body.startswith("{"):
                data = json.loads(body)
                if isinstance(data, dict) and str(data.get("code", "")).startswith("rest_") and "events" not in data:
                    return 404, None
                return 200, data
        raise RuntimeError(f"{full} was blocked {SCRAPER_ATTEMPTS} times through the scraper")

    def _params(self, today: date) -> dict[str, Any]:
        return {
            "per_page": PER_PAGE,
            "start_date": today.isoformat(),
            "end_date": (today + timedelta(days=self.days_ahead)).isoformat() + " 23:59:59",
        }

    async def fetch(self) -> list[RawEvent]:
        self.skipped_far = 0
        out: list[RawEvent] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            url: str | None = self.url
            params: dict[str, Any] | None = self._params(datetime.now(ET).date())
            for _page in range(self.max_pages):
                if not url:
                    break
                status, data = await self._get_json(client, url, params)
                # The API answers past the last page with 404 rest_event_invalid_page.
                if status == 404:
                    if out:
                        break
                    raise RuntimeError(f"{url} has no Events Calendar REST API")
                for event in data.get("events") or []:
                    raw = self._to_raw(event)
                    if raw is not None:
                        out.append(raw)
                # next_rest_url already carries every query param.
                url, params = data.get("next_rest_url"), None
        return out

    def _too_far(self, venue: dict, coords: tuple[float, float] | None) -> bool:
        if coords:
            return _miles(self.center, coords) > self.max_miles
        zip_match = _ZIP_RE.search(" ".join(str(venue.get(k) or "") for k in ("zip", "address", "city")))
        if zip_match and self.nearby_zip_prefixes:
            return not zip_match.group(1).startswith(self.nearby_zip_prefixes)
        return False  # no location at all: can't judge, so keep it

    def _to_raw(self, e: dict) -> RawEvent | None:
        title = _text(e.get("title"))
        start = _local_dt(e.get("start_date"))
        if not title or not start or e.get("status") not in (None, "publish"):
            return None

        venue = e.get("venue") if isinstance(e.get("venue"), dict) else {}
        lat, lng = venue.get("geo_lat"), venue.get("geo_lng")
        try:
            coords = (float(lat), float(lng)) if lat not in (None, "") and lng not in (None, "") else None
        except (TypeError, ValueError):
            coords = None
        if self.max_miles and self._too_far(venue, coords):
            self.skipped_far += 1
            return None

        address = ", ".join(p for p in (venue.get("address"), venue.get("city"), venue.get("stateprovince") or venue.get("state"), venue.get("zip")) if p)
        categories = list(self.default_categories)
        for cat in e.get("categories") or []:
            for mapped in _CATEGORY_MAP.get((html.unescape(cat.get("name") or "")).strip().lower(), []):
                if mapped not in categories:
                    categories.append(mapped)
        price_min, price_max, is_free = _price(e)
        image = e.get("image") if isinstance(e.get("image"), dict) else {}

        return RawEvent(
            source=self.name,
            source_event_id=str(e.get("id")),
            title=title,
            description=_text(e.get("description")),
            start_time=start,
            end_time=_local_dt(e.get("end_date")),
            # An exact-midnight start with all_day unset is an editor who left the
            # time blank (WXPN lists most shows this way), not a 12:00 AM show.
            all_day=bool(e.get("all_day")) or (start.hour, start.minute, start.second) == (0, 0, 0),
            venue_name=_text(venue.get("venue")) or self.venue_name,
            venue_address=address or (self.venue_address if not venue.get("venue") else None),
            latitude=coords[0] if coords else None,
            longitude=coords[1] if coords else None,
            url=e.get("url") or e.get("website"),
            image_url=image.get("url"),
            price_min=price_min,
            price_max=price_max,
            is_free=is_free,
            default_categories=categories,
            raw={"tribe_id": e.get("id"), "cost": e.get("cost")},
        )
