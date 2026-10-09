"""The Today card's weather fact: what the school day will actually feel like
from drop-off to just after pickup, and what that means a kid should bring.

All keyless public sources, all plain httpx (no scraper):
- Census Bureau geocoder - a school's `address` -> lat/lon, once.
- NWS (api.weather.gov) - lat/lon -> forecast office + gridpoint, once; then
  the gridpoint's hourly forecast (temp, chance of precip, conditions).
- EPA Envirofacts - hourly UV index by ZIP. NWS has no UV forecast at all,
  and "does my kid need sunscreen" can't be answered from cloud cover alone.

The advice is deterministic rules over the hours the kid is actually
outside-adjacent (30 min before the bell through an hour after dismissal),
not a daily high/low: a 45° morning and a 70° afternoon need a jacket that
comes home in the backpack, which a "high 70" alone would never suggest.
"""

import asyncio
import logging
import os
import re
import time as _time
from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

import httpx

from services import i18n_strings
from services.kids_view import parse_clock

logger = logging.getLogger(__name__)

LOCAL_TZ = ZoneInfo("America/New_York")
# NWS rejects requests without an identifying User-Agent. A URL is an
# acceptable contact; NWS_CONTACT can add an email without putting one in code.
_USER_AGENT = f"schoolz/1.0 ({os.getenv('NWS_CONTACT') or 'https://schoolz.sitenaut.com'})"
_TIMEOUT = 5.0
_FORECAST_TTL = 60 * 60  # NWS refreshes hourly forecasts about once an hour
_UV_TTL = 3 * 60 * 60
# A failed upstream is remembered briefly too. The EPA UV endpoint answers 404
# for every ZIP (0.5-2s each), and failures used to go uncached, so every Today
# card re-paid that wait on every request.
_FAIL_TTL = 10 * 60

_ZIP_RE = re.compile(r"\b(\d{5})(?:-\d{4})?\b")
_RAIN_RE = re.compile(r"rain|shower|thunder|drizzle|storm", re.IGNORECASE)
_SNOW_RE = re.compile(r"snow|sleet|flurr|ice|wintry|freezing", re.IGNORECASE)

# Minutes before the first bell / after dismissal that count as "outside
# getting to or from school" - the bus stop, the walk, the pickup line.
_BEFORE = timedelta(minutes=30)
_AFTER = timedelta(minutes=60)
_DEFAULT_START = time(8, 0)
_DEFAULT_END = time(15, 0)

_cache: dict[str, tuple[float, object]] = {}
_locks: dict[str, asyncio.Lock] = {}


async def _cached(key: str, ttl: float, fetch):
    """In-process TTL cache, single-flighted per key: the Today feed is public
    and one request per school, so without this every visitor would trigger
    an NWS call. Schools sharing a gridpoint share one entry."""
    hit = _cache.get(key)
    if hit and hit[0] > _time.monotonic():
        return hit[1]
    lock = _locks.setdefault(key, asyncio.Lock())
    async with lock:
        hit = _cache.get(key)
        if hit and hit[0] > _time.monotonic():
            return hit[1]
        try:
            value = await fetch()
        except Exception as exc:
            logger.warning("weather_fetch_failed", extra={"cache_key": key, "error": str(exc)})
            _cache[key] = (_time.monotonic() + _FAIL_TTL, None)
            return None
        if value is not None:
            _cache[key] = (_time.monotonic() + ttl, value)
        return value


def zip_from_address(address: str | None) -> str | None:
    matches = _ZIP_RE.findall(address or "")
    return matches[-1] if matches else None


async def geocode(client: httpx.AsyncClient, address: str) -> tuple[float, float] | None:
    """Census first (exact street match), then OpenStreetMap's Nominatim for
    the full address and finally just the town/ZIP. Street precision doesn't
    matter here - an NWS gridpoint is ~2.5 km - but some real addresses
    aren't in Census's street ranges at all (confirmed: "300 Old Orchard
    Road, Cherry Hill") and some scans only captured the town ("Westmont, NJ")."""
    resp = await client.get(
        "https://geocoding.geo.census.gov/geocoder/locations/onelineaddress",
        params={"address": address, "benchmark": "Public_AR_Current", "format": "json"},
    )
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
        resp = await client.get(
            "https://nominatim.openstreetmap.org/search",
            params={"q": query, "format": "json", "limit": 1, "countrycodes": "us"},
            headers={"User-Agent": _USER_AGENT},
        )
        resp.raise_for_status()
        hits = resp.json()
        if hits:
            return round(float(hits[0]["lat"]), 4), round(float(hits[0]["lon"]), 4)
    return None


async def resolve_grid(client: httpx.AsyncClient, lat: float, lon: float) -> str | None:
    resp = await client.get(f"https://api.weather.gov/points/{lat},{lon}", headers={"User-Agent": _USER_AGENT})
    resp.raise_for_status()
    props = resp.json().get("properties") or {}
    if not props.get("gridId"):
        return None
    return f"{props['gridId']}/{props['gridX']},{props['gridY']}"


async def ensure_location(school) -> str | None:
    """Fills school.latitude/longitude/nws_grid when missing. Returns a short
    note of what it did, or None if there was nothing to do. Never raises -
    a failed lookup just leaves the fields empty for the next run."""
    if school.nws_grid or not school.address:
        return None
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            if school.latitude is None or school.longitude is None:
                coords = await geocode(client, school.address)
                if not coords:
                    return "no geocode match for address"
                school.latitude, school.longitude = coords
            school.nws_grid = await resolve_grid(client, school.latitude, school.longitude)
    except Exception as exc:
        logger.warning("weather_location_failed", extra={"school_id": school.id, "error": str(exc)})
        return f"weather location lookup failed: {type(exc).__name__}"
    return f"weather grid {school.nws_grid}" if school.nws_grid else "no NWS gridpoint"


async def hourly_forecast(grid: str) -> list[dict] | None:
    async def fetch():
        office, xy = grid.split("/")
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                f"https://api.weather.gov/gridpoints/{office}/{xy}/forecast/hourly",
                headers={"User-Agent": _USER_AGENT, "Accept": "application/geo+json"},
            )
            resp.raise_for_status()
        periods = []
        for p in resp.json().get("properties", {}).get("periods") or []:
            periods.append(
                {
                    "start": datetime.fromisoformat(p["startTime"]).astimezone(LOCAL_TZ),
                    "temp": p.get("temperature"),
                    "pop": (p.get("probabilityOfPrecipitation") or {}).get("value") or 0,
                    "forecast": p.get("shortForecast") or "",
                }
            )
        return periods

    return await _cached(f"nws:{grid}", _FORECAST_TTL, fetch)


async def hourly_uv(lat: float, lon: float) -> dict[datetime, int] | None:
    # Open-Meteo (free, keyless, hourly uv_index by coordinate). Rounded to two
    # decimals (~1 km) so neighbouring schools share one cached entry.
    lat, lon = round(lat, 2), round(lon, 2)

    async def fetch():
        async with httpx.AsyncClient(timeout=_TIMEOUT, follow_redirects=True) as client:
            resp = await client.get(
                "https://api.open-meteo.com/v1/forecast",
                params={"latitude": lat, "longitude": lon, "hourly": "uv_index", "timezone": "America/New_York", "forecast_days": 4},
            )
            resp.raise_for_status()
        hourly = resp.json().get("hourly") or {}
        out = {}
        for stamp, value in zip(hourly.get("time") or [], hourly.get("uv_index") or []):
            if value is None:
                continue
            try:
                out[datetime.fromisoformat(stamp).replace(tzinfo=LOCAL_TZ)] = round(value)
            except ValueError:
                continue
        return out

    return await _cached(f"uv:{lat},{lon}", _UV_TTL, fetch)


def school_window(school, status: str, day: date) -> tuple[datetime, datetime, datetime, datetime]:
    """(window_start, bell, dismissal, window_end) in local time. The bell and
    dismissal follow a delayed opening / early dismissal when today is one."""
    start = parse_clock(school.delayed_opening_time if status == "delayed" else None) or parse_clock(school.start_time)
    end = parse_clock(school.early_dismissal_time if status == "early_dismissal" else None) or parse_clock(school.end_time)
    bell = datetime.combine(day, start or _DEFAULT_START, LOCAL_TZ)
    dismissal = datetime.combine(day, end or _DEFAULT_END, LOCAL_TZ)
    return bell - _BEFORE, bell, dismissal, dismissal + _AFTER


def _hour_label(dt: datetime) -> str:
    return f"{(dt.hour - 1) % 12 + 1} {'AM' if dt.hour < 12 else 'PM'}"


def _period_at(periods: list[dict], moment: datetime) -> dict | None:
    return next((p for p in periods if p["start"] <= moment < p["start"] + timedelta(hours=1)), None)


def summarize(
    periods: list[dict],
    uv: dict[datetime, int] | None,
    window: tuple[datetime, datetime, datetime, datetime],
    known_hours: tuple[bool, bool] = (True, True),
) -> dict | None:
    """Pure: the hourly periods overlapping the school-day window -> the
    card's numbers and the things to bring. None when the forecast doesn't
    cover the window (NWS hourly runs ~6 days out; a stale cache after
    midnight can also miss the morning). `known_hours` says whether the bell
    and dismissal are the school's real times or the defaults - a default is
    labeled "Morning"/"Afternoon", never shown as if it were the real bell."""
    window_start, bell, dismissal, window_end = window
    hours = [p for p in periods if p["start"] < window_end and p["start"] + timedelta(hours=1) > window_start and p["temp"] is not None]
    if not hours:
        return None

    temps = [p["temp"] for p in hours]
    low, high = min(temps), max(temps)
    rain_hours = [p for p in hours if p["pop"] >= 40 and _RAIN_RE.search(p["forecast"])]
    snow = any(p["pop"] >= 30 and _SNOW_RE.search(p["forecast"]) for p in hours)
    uv_in_window = [v for h, v in (uv or {}).items() if window_start <= h < window_end]
    uv_max = max(uv_in_window) if uv_in_window else None

    items: list[str] = []
    if low <= 35:
        items.append("heavy_coat")
    elif low <= 50:
        items.append("coat")
    elif low <= 60:
        items.append("jacket")
    elif high - low >= 15:
        items.append("layers")
    if low <= 32:
        items.append("hat_gloves")
    if rain_hours:
        items.append("umbrella")
    if snow:
        items.append("boots")
    if uv_max is not None and uv_max >= 6:
        items.append("sunscreen")
    if uv_max is not None and uv_max >= 8:
        items.append("sun_hat")
    if high >= 85:
        items.append("water")

    midday = _period_at(hours, bell.replace(hour=12, minute=0)) or hours[len(hours) // 2]
    dropoff = _period_at(hours, bell)
    dropoff_label = bell.strftime("%-I:%M %p") if known_hours[0] else "Morning"
    if dropoff is None and bell < hours[0]["start"]:
        # NWS's hourly forecast starts at the current hour, so once drop-off
        # has passed there is no period for the bell - the card showed "–".
        # The current hour is the honest number to show, labeled as such.
        dropoff, dropoff_label = hours[0], "Now"
    pickup = _period_at(hours, dismissal)
    return {
        "dropoff_label": dropoff_label,
        "dropoff_temp": dropoff["temp"] if dropoff else None,
        "pickup_label": dismissal.strftime("%-I:%M %p") if known_hours[1] else "Afternoon",
        "pickup_temp": pickup["temp"] if pickup else None,
        "low": low,
        "high": high,
        "rain_chance": max(p["pop"] for p in hours),
        "rain_from": _hour_label(rain_hours[0]["start"]) if rain_hours else None,
        "condition": midday["forecast"],
        "uv_max": uv_max,
        "items": items,
    }


def pick_weather_day(school, today: date, today_status: str, next_day: date, next_status: str, now: datetime) -> tuple[date, str, bool]:
    """(day, its status, is_today). Today's weather until today's window
    closes; after that - the evening, when clothes get laid out - and all
    day on weekends and closed days, the next school day's."""
    if today_status not in ("weekend", "closed") and now < school_window(school, today_status, today)[3]:
        return today, today_status, True
    return next_day, next_status, False


async def today_weather(school, status: str, day: date, lang: str = "en") -> dict | None:
    """The Today card's weather, or None. Never raises and never waits more
    than a few seconds - a slow NWS must not hold up the whole card."""
    if not school.nws_grid or status in ("weekend", "closed"):
        return None
    try:
        periods, uv = await asyncio.wait_for(
            asyncio.gather(
                hourly_forecast(school.nws_grid),
                hourly_uv(school.latitude, school.longitude) if school.latitude is not None and school.longitude is not None else asyncio.sleep(0, result=None),
                return_exceptions=True,
            ),
            timeout=_TIMEOUT + 1,
        )
    except asyncio.TimeoutError:
        logger.warning("weather_timeout", extra={"school_id": school.id})
        return None
    if isinstance(periods, BaseException) or not periods:
        if isinstance(periods, BaseException):
            logger.warning("weather_forecast_failed", extra={"school_id": school.id, "error": str(periods)})
        return None
    if isinstance(uv, BaseException):
        uv = None
    known = (bool(parse_clock(school.start_time)), bool(parse_clock(school.end_time)))
    summary = summarize(periods, uv, school_window(school, status, day), known)
    return i18n_strings.localize_weather(summary, lang) if summary else None
