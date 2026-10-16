"""NJ 211 (search.nj211.org) - the resource directory adapter.

NJ 211 curates ~6,300 New Jersey programs. There is no public API, so this
reads the public search site the way a visitor's browser does, under rules
that keep it a polite guest (docs/LOCALZ_DESIGN.md, "NJ 211 adapter"):

- robots.txt is read at the start of every run: a run aborts if /search is
  disallowed, and its Crawl-delay (10 s today) is a floor under ours.
- One request at a time, at least `delay_seconds` apart. Never /api/.
- An honest User-Agent naming schoolz and a contact URL, so NJ 211 can tell
  us to stop. A 403 or 429 stops the run (`Blocked`) instead of retrying.

The site is Connect 211's Next.js app. Search and detail pages are
server-rendered into the React Server Components payload - a series of
`self.__next_f.push([1, "<JSON string>"])` scripts that concatenate into
one text stream - so plain httpx works and no browser is needed. Each chunk
is a JSON string literal: decode it with json.loads (unicode_escape mangles
UTF-8, "Jersey\\u00c2\\u00a0City").

Search: `/search?query=<taxonomy code>&query_type=taxonomy&location=<label>
&coords=<lon>,<lat>&page=<n>`, 25 a page. Codes match as prefixes ("B" is
every Basic Needs service) and location means "serves this place", not a
radius, so the crawl walks top-level codes per place.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import re
import time
import urllib.robotparser
from datetime import date, datetime
from typing import Any
from urllib.parse import urlencode

import httpx
from bs4 import BeautifulSoup

SOURCE = "nj211"
BASE_URL = "https://search.nj211.org"
USER_AGENT = "schoolz-localz/1.0 (+https://schoolz.sitenaut.com/contact)"
ROBOTS_AGENT = "schoolz-localz"
PAGE_SIZE = 25
MIN_DELAY_SECONDS = 10.0

# A JSON string literal, escapes included - not `".*?"`, which stops early at
# an escaped quote followed by "])".
_PUSH_RE = re.compile(r'self\.__next_f\.push\(\[1,("(?:[^"\\]|\\.)*")\]\)', re.S)
_TOTAL_RE = re.compile(r'"totalResults":(\d+)')


class Blocked(Exception):
    """NJ 211 refused us (403/429) or robots.txt now disallows /search.
    Stop for this run; never retry harder."""


# ---- parsing --------------------------------------------------------------


def decode_payload(html: str) -> str:
    chunks = _PUSH_RE.findall(html)
    if not chunks:
        raise ValueError("no Next.js payload in page - layout changed?")
    return "".join(json.loads(c) for c in chunks)


def parse_search_page(html: str) -> tuple[list[dict], int]:
    """The results on one search page and the total for the whole query."""
    text = decode_payload(html)
    match = _TOTAL_RE.search(text)
    if not match:
        raise ValueError("search page has no totalResults - layout changed?")
    total = int(match.group(1))
    start = text.rfind('"results":[', 0, match.start())
    if start < 0:
        if total == 0:
            return [], 0
        raise ValueError("search page has a total but no results array - layout changed?")
    results, _ = json.JSONDecoder().raw_decode(text, start + len('"results":'))
    if not isinstance(results, list):
        raise ValueError("search results are not a list")
    return [r for r in results if isinstance(r, dict) and r.get("id")], total


def parse_detail_page(html: str, record_id: str) -> dict:
    text = decode_payload(html)
    decoder = json.JSONDecoder()
    for match in re.finditer(r'\{"id":"' + re.escape(record_id) + '"', text):
        try:
            obj, _ = decoder.raw_decode(text, match.start())
        except ValueError:
            continue
        if isinstance(obj, dict) and obj.get("serviceName") is not None:
            return obj
    raise ValueError(f"detail page has no record {record_id} - layout changed?")


# ---- normalization --------------------------------------------------------


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
    return text or None


def _plain(html: Any) -> str | None:
    """Descriptions arrive as HTML ("<p>Provides ...</p>")."""
    if not html:
        return None
    return _clean(BeautifulSoup(str(html), "html.parser").get_text(" "))


def _strings(values: Any) -> list[str]:
    out: list[str] = []
    for v in values or []:
        if isinstance(v, dict):
            v = v.get("name") or v.get("language") or v.get("value")
        text = _clean(v)
        if text and text not in out:
            out.append(text)
    return out


def organization_from_name(name: str | None, service_name: str | None) -> str | None:
    """Search results carry "<service> | <organization>" in `name`."""
    name = _clean(name)
    if not name:
        return None
    if " | " in name:
        return _clean(name.split(" | ", 1)[1])
    return name if name != _clean(service_name) else None


def _taxonomies(items: Any) -> tuple[list[str], list[str]]:
    codes: list[str] = []
    names: list[str] = []
    for item in items or []:
        if not isinstance(item, dict):
            continue
        code = _clean(item.get("code"))
        if code and code not in codes:
            codes.append(code)
            names.append(_clean(item.get("name")) or code)
    return codes, names


def _coords(location: Any) -> tuple[float | None, float | None]:
    try:
        lon, lat = (location or {}).get("coordinates") or (None, None)
        return (float(lat), float(lon)) if lat is not None and lon is not None else (None, None)
    except (TypeError, ValueError):
        return None, None


def _assured_on(value: Any) -> date | None:
    text = _clean(value)
    if not text:
        return None
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def summary_hash(result: dict) -> str:
    """What a search listing says about a record. A change means the full
    record is worth fetching again."""
    keys = ("serviceName", "name", "locationName", "description", "phone", "website", "address", "eligibility", "applicationProcess", "hours")
    basis = {k: result.get(k) for k in keys}
    basis["taxonomies"] = sorted(t.get("code") or "" for t in result.get("taxonomies") or [] if isinstance(t, dict))
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()


def summary_fields(result: dict) -> dict:
    """ResourceService fields from a search listing (the first sight of a
    record; the detail page fills in the rest)."""
    codes, names = _taxonomies(result.get("taxonomies"))
    lat, lon = _coords(result.get("location"))
    return {
        "name": _clean(result.get("serviceName")) or _clean(result.get("name")) or "Unnamed service",
        "organization_name": organization_from_name(result.get("name"), result.get("serviceName")),
        "location_name": _clean(result.get("locationName")),
        "description": _plain(result.get("description")),
        "phone": _clean(result.get("phone")),
        "website": _clean(result.get("website")),
        "address": _clean(result.get("address")),
        "latitude": lat,
        "longitude": lon,
        "hours_text": _clean(result.get("hours")),
        "eligibility_text": _clean(result.get("eligibility")),
        "application_process": _plain(result.get("applicationProcess")),
        "taxonomy_codes": codes,
        "taxonomy_names": names,
    }


def _physical_address(record: dict) -> dict:
    addresses = [a for a in record.get("addresses") or [] if isinstance(a, dict)]
    addresses.sort(key=lambda a: (a.get("type") != "physical", a.get("rank") or 0))
    return addresses[0] if addresses else {}


def _voice_phone(record: dict) -> str | None:
    phones = [p for p in record.get("phoneNumbers") or [] if isinstance(p, dict) and p.get("number")]
    phones.sort(key=lambda p: (p.get("type") not in (None, "voice"), p.get("rank") or 0))
    return _clean(phones[0]["number"]) if phones else _clean(record.get("phone"))


def detail_fields(record: dict) -> dict:
    """ResourceService fields from a full record (detail page)."""
    codes, names = _taxonomies(record.get("categories") or record.get("taxonomies"))
    lat, lon = _coords(record.get("location"))
    addr = _physical_address(record)
    street = ", ".join(p for p in (_clean(addr.get("address_1")), _clean(addr.get("address_2"))) if p) or _clean(record.get("address"))
    areas = [a for a in (_clean(line) for line in str(record.get("serviceAreaName") or "").splitlines()) if a]
    fields = {
        "name": _clean(record.get("serviceName")) or _clean(record.get("name")) or "Unnamed service",
        "organization_name": _clean(record.get("organizationName"))
        or organization_from_name(record.get("name"), record.get("serviceName")),
        "location_name": _clean(record.get("locationName")),
        "description": _plain(record.get("description")),
        "phone": _voice_phone(record),
        "email": _clean(record.get("email")),
        "website": _clean(record.get("website")),
        "address": street,
        "city": _clean(addr.get("city")),
        "postal_code": _clean(addr.get("postalCode")),
        "latitude": lat,
        "longitude": lon,
        "hours_text": _clean(record.get("hours")) or _clean(record.get("hoursDescription")),
        "eligibility_text": _clean(record.get("eligibilities")) or _clean(record.get("eligibility")),
        "application_process": _plain(record.get("applicationProcess")),
        "fees": _clean(record.get("fees")),
        "required_documents": _strings(record.get("requiredDocuments")),
        "languages": _strings(record.get("languages")),
        "accessibility": _plain(record.get("accessibility")),
        "transportation": _plain(record.get("transportation")),
        "service_areas": areas,
        "alert": _plain(record.get("alert")),
        "last_assured_on": _assured_on(record.get("lastAssuredOn")),
    }
    if codes:
        fields["taxonomy_codes"] = codes
        fields["taxonomy_names"] = names
    return fields


def organization_fields(record: dict) -> dict:
    return {
        "name": _clean(record.get("organizationName")) or organization_from_name(record.get("name"), record.get("serviceName")),
        "alternate_name": _clean(record.get("organizationAlternateName")),
        "description": _plain(record.get("organizationDescription")),
        "url": _clean(record.get("organizationUrl")),
    }


def storable_raw(record: dict) -> dict:
    """The record as kept in `raw`: minus the service-area polygon (large,
    and `service_areas` holds the county list) and `contacts`, which can
    name staff - people's names are never stored."""
    return {k: v for k, v in record.items() if k not in ("serviceArea", "contacts", "tenantId")}


# ---- client ---------------------------------------------------------------


def search_path(code: str, place: dict, page: int = 1) -> str:
    query = {
        "query": code,
        "query_type": "taxonomy",
        "location": place["label"],
        "coords": f"{place['lon']},{place['lat']}",
    }
    if page > 1:
        query["page"] = page
    return "/search?" + urlencode(query)


class NJ211Client:
    """One request at a time, spaced by the larger of `delay_seconds` and
    robots.txt's Crawl-delay."""

    def __init__(self, delay_seconds: float = MIN_DELAY_SECONDS, http: httpx.AsyncClient | None = None, sleep=asyncio.sleep, clock=time.monotonic):
        self.delay = max(float(delay_seconds), MIN_DELAY_SECONDS)
        self._http = http
        self._owns_http = http is None
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.requests = 0

    async def __aenter__(self) -> NJ211Client:
        if self._http is None:
            self._http = httpx.AsyncClient(
                base_url=BASE_URL,
                timeout=httpx.Timeout(45.0, connect=10.0),
                headers={"Accept": "text/html,application/xhtml+xml"},
                follow_redirects=True,
            )
        return self

    async def __aexit__(self, *exc) -> None:
        if self._owns_http and self._http is not None:
            await self._http.aclose()

    async def _get(self, path: str) -> httpx.Response:
        if path.startswith("/api/") or path.startswith("/admin/"):
            raise ValueError(f"refusing to request {path}: disallowed by robots.txt")
        if self._last_request is not None:
            wait = self.delay - (self._clock() - self._last_request)
            if wait > 0:
                await self._sleep(wait)
        self._last_request = self._clock()
        self.requests += 1
        # Per request, so it holds whatever client was passed in.
        resp = await self._http.get(path, headers={"User-Agent": USER_AGENT})
        if resp.status_code in (403, 429):
            raise Blocked(f"NJ 211 answered {resp.status_code} for {path}")
        return resp

    async def check_robots(self) -> None:
        resp = await self._get("/robots.txt")
        if resp.status_code >= 400:
            return  # no robots.txt: nothing disallowed
        parser = urllib.robotparser.RobotFileParser()
        parser.parse(resp.text.splitlines())
        if not parser.can_fetch(ROBOTS_AGENT, f"{BASE_URL}/search?query=B"):
            raise Blocked("robots.txt disallows /search")
        crawl_delay = parser.crawl_delay(ROBOTS_AGENT)
        if crawl_delay:
            self.delay = max(self.delay, float(crawl_delay))

    async def search(self, code: str, place: dict, page: int = 1) -> tuple[list[dict], int]:
        resp = await self._get(search_path(code, place, page))
        resp.raise_for_status()
        return parse_search_page(resp.text)

    async def detail(self, record_id: str) -> dict:
        if not re.fullmatch(r"[0-9A-Za-z-]{8,64}", record_id or ""):
            raise ValueError(f"not an NJ 211 record id: {record_id!r}")
        resp = await self._get(f"/search/{record_id}")
        resp.raise_for_status()
        return parse_detail_page(resp.text, record_id)
