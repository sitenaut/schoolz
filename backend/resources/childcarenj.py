"""ChildCareNJ.gov - the state's child care provider directory adapter.

NJ 211 lists the help around child care (subsidy agencies, Head Start
offices) but not individual daycares; ChildCareNJ (NJ Department of Human
Services) lists every licensed center, registered family child care home
and licensed camp, with structured hours, ages, Grow NJ Kids rating and
whether the provider takes state child care assistance (CCAP).

Read through the search page's own JSON call (docs/LOCALZ_DESIGN.md,
"ChildCareNJ adapter"): `GET /Services/GetProviders.aspx`, one request per
county (500 a page is accepted, and no county has more). The endpoint
redirects to an error page unless it gets the full parameter set the page
sends - sortKey and all. There's no robots.txt; one request at a time,
`delay_seconds` apart, the same honest User-Agent as the NJ 211 adapter,
and a 403/429 stops the run.

**Registered family child care is someone's home.** The state already
leaves those street addresses blank; this adapter never stores one, never
stores any provider's email (often a personal address), and keeps them at
town level.
"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import re
import time
from typing import Any

import httpx

from .nj211 import USER_AGENT

logger = logging.getLogger(__name__)

SOURCE = "childcarenj"
SOURCE_NAME = "ChildCareNJ"
BASE_URL = "https://www.childcarenj.gov"
PAGE_SIZE = 500
# Part of every record's hash: bump it when `fields()` changes, so the next
# run rewrites providers whose source record didn't change.
NORMALIZE_VERSION = 2
MIN_DELAY_SECONDS = 5.0

NJ_COUNTIES = [
    "Atlantic", "Bergen", "Burlington", "Camden", "Cape May", "Cumberland", "Essex",
    "Gloucester", "Hudson", "Hunterdon", "Mercer", "Middlesex", "Monmouth", "Morris",
    "Ocean", "Passaic", "Salem", "Somerset", "Sussex", "Union", "Warren",
]

# Copied from the `looupTable` object on childcarenj.gov/Search (the page
# decodes the JSON's numeric codes with it). A code missing here is reported
# in the run summary, never dropped silently.
FACILITY_TYPES = {1: "Licensed child care center", 2: "Registered family child care", 3: "Group child care"}
AGE_GROUPS = {1: "infants", 2: "toddlers", 3: "preschoolers", 4: "school-age children", 5: None, 0: None, 1000: "children up to 13"}
PROGRAMS = {
    1: "Takes part in Head Start.",
    2: "Takes part in the state preschool program.",
    3: "Accepts state child care assistance (CCAP).",
    4: "Accepts private scholarships.",
}
SCHEDULES = {
    1: "evenings", 2: "overnight", 3: "weekends", 4: "holidays", 5: "sick care", 6: "drop-in",
    7: "special needs", 8: "nights", 9: "temporary care", 10: "emergency care",
    11: "intermittent care", 12: "rotating shifts",
}
DISCOUNTS = {1: "sibling discount", 2: "employee discount", 3: "sliding scale", 4: "military family discount"}
YEARLY = {1: "Full year", 2: "School year", 3: "Summer only"}
RATINGS = {n: f"Grow NJ Kids level {n}" for n in range(1, 7)} | {991: "Grow NJ Kids: taking part, not yet rated"}
CCAP = 3

# Localz's Type filter matches one code exactly. Centers and camps use the
# Inform USA codes NJ 211 uses for them; family child care, which NJ 211
# doesn't list, takes the parent code rather than a guessed leaf code.
TYPE_TAXONOMY = {
    "center": ("PH-1250.1400", "Child Care Centers"),
    "home": ("PH-1250", "Family Child Care"),
    "camp": ("PL-6400.1500-820", "Summer Camps"),
}
_KEEP_UPPER = {"LLC", "INC", "YMCA", "YWCA", "JCC", "ABC", "NJ", "II", "III", "IV", "USA", "KC", "CC", "DBA"}

DAYS = [("Monday", "Mon"), ("Tuesday", "Tue"), ("Wednesday", "Wed"), ("Thursday", "Thu"), ("Friday", "Fri"), ("Saturday", "Sat"), ("Sunday", "Sun")]
TUITION = [("Infant", "Infants"), ("Toddler", "Toddlers"), ("Preschool", "Preschool"), ("SchoolAge", "School age")]
# One price per age group: weekly when there is one, as parents compare.
TUITION_UNITS = [("Weekly", "week"), ("Monthly", "month"), ("Daily", "day"), ("Hourly", "hour")]

# Never stored, even in `raw`.
_PRIVATE_KEYS = ("ProgramEmail",)
_HOME_KEYS = ("ProgramAddressStreetNumber", "ProgramAddressStreetName")


class Blocked(Exception):
    """ChildCareNJ refused us (403/429). Stop for this run; never retry harder."""


# ---- normalization --------------------------------------------------------


def _clean(value: Any) -> str | None:
    if value is None:
        return None
    text = re.sub(r"\s+", " ", str(value).replace("\xa0", " ")).strip()
    return text or None


def _codes(values: Any) -> list[int]:
    out = []
    for v in values or []:
        try:
            out.append(int(v))
        except (TypeError, ValueError):
            continue
    return out


def _decode(values: Any, table: dict[int, str | None], field: str, unknown: set[str]) -> list[str]:
    out = []
    for code in _codes(values):
        if code not in table:
            unknown.add(f"{field}={code}")
            continue
        if table[code]:
            out.append(table[code])
    return out


def is_home(record: dict) -> bool:
    return _codes([record.get("ProgramFacilityType")]) == [2]


def kind(record: dict) -> str:
    if is_home(record):
        return "home"
    if (_clean(record.get("LicenseNumber")) or "").upper().startswith("CMP") or _codes([record.get("YearlySchedule")]) == [3]:
        return "camp"
    return "center"


def _time(value: Any) -> str | None:
    match = re.match(r"^(\d{1,2}):(\d{2})", _clean(value) or "")
    if not match:
        return None
    hour, minute = int(match.group(1)), match.group(2)
    suffix = "AM" if hour < 12 else "PM"
    return f"{(hour % 12) or 12}:{minute} {suffix}"


def hours_text(record: dict) -> str | None:
    """"Mon-Fri 7:00 AM-6:00 PM; Sat 8:00 AM-12:00 PM", runs of days with the
    same hours folded together."""
    spans: list[tuple[str, str | None]] = []
    for day, short in DAYS:
        opens, closes = _time(record.get(f"DailyOpeningTime{day}")), _time(record.get(f"DailyClosingTime{day}"))
        spans.append((short, f"{opens}-{closes}" if opens and closes else None))
    parts: list[str] = []
    i = 0
    while i < len(spans):
        short, hours = spans[i]
        j = i
        while j + 1 < len(spans) and spans[j + 1][1] == hours:
            j += 1
        if hours:
            parts.append(f"{short}-{spans[j][0]} {hours}" if j > i else f"{short} {hours}")
        i = j + 1
    return "; ".join(parts) or None


def _money(amount: float) -> str:
    return f"${amount:,.0f}" if float(amount).is_integer() else f"${amount:,.2f}"


def fees_text(record: dict, unknown: set[str]) -> str | None:
    parts = []
    for key, label in TUITION:
        for unit_key, unit in TUITION_UNITS:
            try:
                amount = float(record.get(f"Tuition{key}{unit_key}") or 0)
            except (TypeError, ValueError):
                continue
            if amount > 0:
                parts.append(f"{label}: {_money(amount)}/{unit}")
                break
    discounts = _decode(record.get("DiscountsAvailable"), DISCOUNTS, "DiscountsAvailable", unknown)
    if discounts:
        parts.append("Discounts: " + ", ".join(discounts))
    if CCAP in _codes(record.get("ParticipationInLocalStateOrFederalPrograms")):
        parts.append("Accepts state child care assistance (CCAP)")
    return ". ".join(parts) or None


def ages(record: dict, unknown: set[str]) -> list[str]:
    return _decode(record.get("AgesLicensedToServe"), AGE_GROUPS, "AgesLicensedToServe", unknown)


def _join(words: list[str]) -> str:
    return words[0] if len(words) == 1 else ", ".join(words[:-1]) + " and " + words[-1]


def eligibility_text(record: dict, unknown: set[str]) -> str | None:
    served = ages(record, unknown)
    return f"Cares for {_join(served)}." if served else None


def description(record: dict, unknown: set[str]) -> str:
    facility = _decode([record.get("ProgramFacilityType")], FACILITY_TYPES, "ProgramFacilityType", unknown)
    label = "Licensed youth camp" if kind(record) == "camp" else (facility[0] if facility else "Child care provider")
    lines = [label + "."]
    served = ages(record, unknown)
    if served:
        lines.append(f"Ages: {_join(served)}.")
    yearly = _decode([record.get("YearlySchedule")] if record.get("YearlySchedule") else [], YEARLY, "YearlySchedule", unknown)
    if yearly:
        lines.append(f"{yearly[0]}.")
    programs = _decode(record.get("ParticipationInLocalStateOrFederalPrograms"), PROGRAMS, "ParticipationInLocalStateOrFederalPrograms", unknown)
    lines.extend(programs)
    schedules = _decode(record.get("SpecialSchedules"), SCHEDULES, "SpecialSchedules", unknown)
    if schedules:
        lines.append(f"Also offers: {_join(schedules)}.")
    rating = _codes([record.get("QualityRating")])
    if rating and rating[0] in RATINGS:
        lines.append(f"{RATINGS[rating[0]]}.")
    try:
        capacity = int(record.get("ProgramLicensedCapacityTotal") or 0)
    except (TypeError, ValueError):
        capacity = 0
    if capacity:
        lines.append(f"Licensed for {capacity} children.")
    return " ".join(lines)


def _phone(record: dict) -> str | None:
    phone = _clean(record.get("ProgramPhoneNumber"))
    ext = _clean(record.get("ProgramPhoneNumberExtension"))
    return f"{phone} ext. {ext}" if phone and ext else phone


def _website(record: dict) -> str | None:
    url = _clean(record.get("ProgramWebsiteLink"))
    if not url or " " in url or "." not in url:
        return None
    return url if re.match(r"^https?://", url, re.I) else f"https://{url}"


def _address(record: dict) -> str | None:
    if is_home(record):
        return None
    return _clean(f"{record.get('ProgramAddressStreetNumber') or ''} {record.get('ProgramAddressStreetName') or ''}")


def display_name(value: Any) -> str | None:
    """"A PRECIOUS DAYCARE" -> "A Precious Daycare". Only names written all
    in capitals are touched; "ABC Learning Station" stays as it is."""
    name = _clean(value)
    if not name or name != name.upper() or not re.search(r"[A-Z]", name):
        return name
    return re.sub(r"[A-Z0-9][A-Z0-9'&.]*", lambda m: m.group(0) if m.group(0).strip(".") in _KEEP_UPPER else m.group(0).capitalize(), name)


def provider_url(record_id: str, license_number: str | None) -> str:
    query = f"uniqueProgramID={record_id}"
    if license_number:
        query += f"&licenseNumber={license_number}"
    return f"{BASE_URL}/providerdetails.aspx?{query}"


def storable_raw(record: dict) -> dict:
    """The source record minus what's never kept: any email, and a home
    provider's street address (blank from the state today)."""
    drop = set(_PRIVATE_KEYS) | (set(_HOME_KEYS) if is_home(record) else set())
    return {k: v for k, v in record.items() if k not in drop}


def record_hash(record: dict) -> str:
    basis = {"v": NORMALIZE_VERSION, "record": storable_raw(record)}
    return hashlib.sha256(json.dumps(basis, sort_keys=True, default=str).encode()).hexdigest()


def fields(record: dict, county: str, unknown: set[str]) -> dict:
    """ResourceService fields from one provider. The list record is the
    whole record: there's no separate detail fetch."""
    code, type_name = TYPE_TAXONOMY[kind(record)]
    name = display_name(record.get("ProgramName")) or "Child care provider"
    return {
        "name": name,
        "organization_name": name,
        "location_name": None,
        "description": description(record, unknown),
        "phone": _phone(record),
        "email": None,
        "website": _website(record),
        "address": _address(record),
        "city": _clean(record.get("ProgramCity")),
        "postal_code": _clean(record.get("ProgramZipCode")),
        "latitude": None,
        "longitude": None,
        "hours_text": hours_text(record),
        "eligibility_text": eligibility_text(record, unknown),
        "application_process": "Call the provider to ask about openings and to arrange a visit.",
        "fees": fees_text(record, unknown),
        "required_documents": [],
        "languages": [s for s in (_clean(v) for v in record.get("LanguagesSpokenByStaff") or []) if s],
        "accessibility": None,
        "transportation": None,
        "service_areas": [f"{county} County, NJ"],
        "taxonomy_codes": [code],
        "taxonomy_names": [type_name],
        "listed_in_counties": [county],
        "alert": None,
        "last_assured_on": None,
    }


# ---- fetching -------------------------------------------------------------


def search_params(county: str, page: int) -> dict:
    # Every parameter the search page sends; with any missing the endpoint
    # redirects to its error page.
    return {
        "zipcode": "",
        "county": county,
        "programName": "",
        "camp": "true",
        "center": "true",
        "home": "true",
        "preschool": "true",
        "rating": "",
        "programTypes": "",
        "subsidised": "false",
        "mccynplus": "false",
        "sortKey": "ProgramName",
        "sortDirection": "ASC",
        "pageSize": PAGE_SIZE,
        "currentPage": page,
    }


def parse_response(body: bytes | str) -> tuple[list[dict], int]:
    data = json.loads(body)
    if not isinstance(data, dict) or not isinstance(data.get("Facilities"), list):
        raise ValueError("no Facilities list in the response - endpoint changed?")
    return [f for f in data["Facilities"] if isinstance(f, dict) and f.get("UniqueProgramID")], int(data.get("ResultCount") or 0)


class ChildCareNJClient:
    """One request at a time, `delay_seconds` apart."""

    def __init__(self, delay_seconds: float = MIN_DELAY_SECONDS, timeout: float = 90.0):
        self.delay = max(float(delay_seconds), MIN_DELAY_SECONDS)
        self.timeout = timeout
        self.requests = 0
        self._last = 0.0
        self._http: httpx.AsyncClient | None = None

    async def __aenter__(self) -> ChildCareNJClient:
        self._http = httpx.AsyncClient(
            timeout=self.timeout,
            headers={
                "User-Agent": USER_AGENT,
                "Accept": "application/json, text/javascript, */*; q=0.01",
                "X-Requested-With": "XMLHttpRequest",
                "Referer": f"{BASE_URL}/Search",
            },
        )
        return self

    async def __aexit__(self, *exc: Any) -> None:
        if self._http is not None:
            await self._http.aclose()

    async def _wait(self) -> None:
        wait = self._last + self.delay - time.monotonic()
        if wait > 0:
            await asyncio.sleep(wait)
        self._last = time.monotonic()

    async def providers(self, county: str, page: int = 0) -> tuple[list[dict], int]:
        assert self._http is not None
        await self._wait()
        self.requests += 1
        response = await self._http.get(f"{BASE_URL}/Services/GetProviders.aspx", params=search_params(county, page))
        if response.status_code in (403, 429):
            raise Blocked(f"HTTP {response.status_code} for {county}")
        if response.status_code != 200 or "json" not in response.headers.get("content-type", ""):
            raise ValueError(f"HTTP {response.status_code} {response.headers.get('content-type', '')} for {county} - endpoint changed?")
        return parse_response(response.content)
