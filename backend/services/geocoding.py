"""Text -> coordinates, on free keyless services.

- Census Bureau geocoder - street addresses. No published rate limit.
- OpenStreetMap Nominatim - everything Census can't place: a town, a ZIP, a
  venue by name. Its usage policy is one request a second with an
  identifying User-Agent, so anything that loops over lookups must pause
  between them (local_events/locate.py does).
"""

import asyncio
import os
import re
import time
from dataclasses import dataclass

import httpx

# NWS and Nominatim both reject requests without an identifying User-Agent. A
# URL is an acceptable contact; NWS_CONTACT can add an email without putting
# one in code.
USER_AGENT = f"schoolz/1.0 ({os.getenv('NWS_CONTACT') or 'https://schoolz.sitenaut.com'})"

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_ZIP_ONLY_RE = re.compile(r"^\s*(\d{5})(?:-\d{4})?\s*$")
_CENSUS_URL = "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress"
_NOMINATIM_URL = "https://nominatim.openstreetmap.org/search"


@dataclass(frozen=True)
class Place:
    latitude: float
    longitude: float
    label: str


_nominatim_lock = asyncio.Lock()
_nominatim_last = 0.0


async def _nominatim(client: httpx.AsyncClient, params: dict) -> dict | None:
    global _nominatim_last
    # One request a second, per process, whoever is asking: one address can
    # take three of these back to back.
    async with _nominatim_lock:
        wait = _nominatim_last + 1.0 - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        try:
            resp = await client.get(
                _NOMINATIM_URL,
                params={"format": "json", "limit": 1, "countrycodes": "us", **params},
                headers={"User-Agent": USER_AGENT},
            )
        finally:
            _nominatim_last = time.monotonic()
    resp.raise_for_status()
    hits = resp.json()
    return hits[0] if hits else None


def _coords(hit: dict) -> tuple[float, float]:
    return round(float(hit["lat"]), 4), round(float(hit["lon"]), 4)


async def geocode(client: httpx.AsyncClient, address: str) -> tuple[float, float] | None:
    """Census first (exact street match), then OpenStreetMap's Nominatim for
    the full address, then just the town, then just the ZIP. Street precision doesn't
    matter to the callers - an NWS gridpoint is ~2.5 km, an events radius is
    miles - but some real addresses aren't in Census's street ranges at all
    (confirmed: "300 Old Orchard Road, Cherry Hill") and some scans only
    captured the town ("Westmont, NJ")."""
    resp = await client.get(_CENSUS_URL, params={"address": address, "benchmark": "Public_AR_Current", "format": "json"})
    resp.raise_for_status()
    matches = resp.json().get("result", {}).get("addressMatches") or []
    if matches:
        coords = matches[0]["coordinates"]
        return round(coords["y"], 4), round(coords["x"], 4)

    parts = [p.strip() for p in address.split(",")]
    # Drop the street only when there's a city left after it - "Westmont, NJ"
    # minus its first part would be just "NJ", i.e. the middle of the state.
    town = ", ".join(parts[1:]) if len(parts) >= 3 else address
    for query in dict.fromkeys((address, town)):
        hit = await _nominatim(client, {"q": query})
        if hit:
            return _coords(hit)
    # Last resort, its ZIP: "Family Center, 2201 Bangor Road, Lindenwold,
    # 08021, United States" defeats both of the above.
    zips = _ZIP_RE.findall(address)
    if zips:
        hit = await _nominatim(client, {"postalcode": zips[-1], "country": "us"})
        if hit:
            return _coords(hit)
    return None


async def geocode_name(client: httpx.AsyncClient, name: str, center: tuple[float, float], degrees: float = 1.0) -> tuple[float, float] | None:
    """A venue known only by name ("Franklin Music Hall"), looked for inside
    a box around `center` and nowhere else - an unbounded name search
    happily returns the same name three states away."""
    lat, lng = center
    hit = await _nominatim(
        client,
        {"q": name, "viewbox": f"{lng - degrees},{lat + degrees},{lng + degrees},{lat - degrees}", "bounded": 1},
    )
    return _coords(hit) if hit else None


async def find_place(client: httpx.AsyncClient, query: str) -> Place | None:
    """What a visitor typed - an address, a town or a ZIP - as a point with a
    short label to show back to them."""
    query = " ".join(query.split())
    zip_only = _ZIP_ONLY_RE.match(query)
    if zip_only:
        hit = await _nominatim(client, {"postalcode": zip_only.group(1), "country": "us"})
        if not hit:
            return None
        # display_name is "08003, Cherry Hill Township, Camden County, ..."
        parts = [p.strip() for p in (hit.get("display_name") or "").split(",")]
        town = next((p for p in parts if p and not p[0].isdigit()), None)
        lat, lng = _coords(hit)
        return Place(lat, lng, f"{town} {zip_only.group(1)}" if town else zip_only.group(1))
    coords = await geocode(client, query)
    return Place(coords[0], coords[1], query) if coords else None
