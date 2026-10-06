"""RunSignup races near a zip code (runsignup.com/races).

The race search has a public JSON API (`/Rest/races`), no key and no
scraper: zipcode + radius + a date window, 250 a page. One RawEvent per
race, not per distance - a 5K with a 1 mile walk is one thing to go to.

RunSignup is also used as a sign-up form for things that aren't a race on a
day, and the search returns them all:

- virtual races, and clubs/season registrations (a CYO basketball season is
  event_type "other") - only in-person event types count, and a race with
  none is skipped;
- records whose dates are stale or missing at the race level (`next_date`
  null on a series whose next leg is months out) - so the date comes from
  the in-person events' own `start_time`, never `next_date`;
- run-it-yourself race mills that list a real trail as the address
  ("Course Map will be emailed"), twice per title - `exclude_patterns`
  (regexes over title + street) is how a job drops those.

A response without a `races` list raises, so an API change is a failed
source (WARNING) rather than a quiet "0 events".

Example job-params entry:

    {
      "name": "runsignup",
      "zipcode": "08002",
      "radius": 15,
      "days_ahead": 120,
      "states": ["NJ"],
      "exclude_patterns": ["course map will be emailed"],
      "default_categories": ["sports"]
    }
"""
from __future__ import annotations

import html as html_lib
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

API_URL = "https://runsignup.com/Rest/races"
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_PAGE_SIZE = 250
_MAX_PAGES = 10
_NOT_IN_PERSON = {"virtual_race", "other"}
_DEFAULT_TZ = "America/New_York"
_MAX_EVENT_HOURS = 48
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"\s+")


def _text(fragment: str | None) -> str:
    if not fragment:
        return ""
    return _WS_RE.sub(" ", html_lib.unescape(_TAG_RE.sub(" ", fragment))).replace("\xa0", " ").strip()


def _dt(value: str | None) -> datetime | None:
    """RunSignup prints 'M/D/YYYY HH:MM', unpadded, in the race's own timezone."""
    if not value:
        return None
    try:
        return datetime.strptime(value.strip(), "%m/%d/%Y %H:%M")
    except ValueError:
        return None


def _fee(value: str | None) -> float | None:
    try:
        return float((value or "").replace("$", "").replace(",", ""))
    except ValueError:
        return None


def _current_fee(event: dict, now: datetime) -> float | None:
    periods = [p for p in event.get("registration_periods") or [] if isinstance(p, dict)]
    for period in periods:
        opens, closes = _dt(period.get("registration_opens")), _dt(period.get("registration_closes"))
        if opens and closes and opens <= now <= closes:
            return _fee(period.get("race_fee"))
    return _fee(periods[-1].get("race_fee")) if periods else None


def _address(address: dict) -> str | None:
    city_line = " ".join(p for p in (address.get("state"), address.get("zipcode")) if p)
    parts = [address.get("street"), address.get("city"), city_line]
    return ", ".join(p.strip() for p in parts if p and p.strip()) or None


def parse_races(
    payload: dict,
    source: str,
    *,
    today: date,
    days_ahead: int = 120,
    states: list[str] | None = None,
    exclude_patterns: list[str] | None = None,
    default_categories: list[str] | None = None,
) -> list[RawEvent]:
    if not isinstance(payload, dict) or not isinstance(payload.get("races"), list):
        raise ValueError("no 'races' list in the RunSignup response")
    horizon = today + timedelta(days=days_ahead)
    wanted_states = {s.upper() for s in states or []}
    excludes = [re.compile(p, re.I) for p in exclude_patterns or []]

    out: list[RawEvent] = []
    seen: set[str] = set()
    for row in payload["races"]:
        race = (row or {}).get("race") or {}
        name = _text(race.get("name"))
        if not race.get("race_id") or not name:
            continue
        if race.get("is_draft_race") == "T" or race.get("is_private_race") == "T":
            continue
        address = race.get("address") or {}
        if wanted_states and (address.get("state") or "").upper() not in wanted_states:
            continue
        haystack = f"{name} {address.get('street') or ''}"
        if any(p.search(haystack) for p in excludes):
            continue

        in_person = []
        for event in race.get("events") or []:
            start = _dt((event or {}).get("start_time"))
            if start is None or event.get("volunteer") == "T" or event.get("event_type") in _NOT_IN_PERSON:
                continue
            if today <= start.date() <= horizon:
                in_person.append((start, event))
        if not in_person:
            continue
        in_person.sort(key=lambda pair: pair[0])
        start, _first = in_person[0]
        same_day = [(s, e) for s, e in in_person if s.date() == start.date()]

        event_id = f"{race['race_id']}-{start:%Y%m%d}"
        if event_id in seen:
            continue
        seen.add(event_id)

        try:
            tz = ZoneInfo(race.get("timezone") or _DEFAULT_TZ)
        except Exception:
            tz = ZoneInfo(_DEFAULT_TZ)
        # A start of exactly midnight is "no time given", not a midnight race.
        all_day = all(s.hour == 0 and s.minute == 0 for s, _ in same_day)
        if not all_day:
            start = min(s for s, _ in same_day if (s.hour, s.minute) != (0, 0))
        # A series prints its last leg as the end time; that isn't how long day one runs.
        ends = [
            e
            for e in (_dt(ev.get("end_time")) for _, ev in same_day)
            if e and start < e <= start + timedelta(hours=_MAX_EVENT_HOURS)
        ]

        now = datetime.combine(today, datetime.min.time())
        fees = [f for f in (_current_fee(ev, now) for _, ev in same_day) if f is not None]
        distances = list(dict.fromkeys(_text(ev.get("distance") or ev.get("name")) for _, ev in same_day))
        description = _text(race.get("description"))
        if distances:
            description = " ".join(p for p in (", ".join(d for d in distances if d) + ".", description) if p)

        out.append(
            RawEvent(
                source=source,
                source_event_id=event_id,
                title=name,
                description=description or None,
                start_time=start.replace(tzinfo=tz),
                end_time=max(ends).replace(tzinfo=tz) if ends and not all_day else None,
                all_day=all_day,
                venue_address=_address(address),
                url=race.get("url"),
                image_url=race.get("logo_url"),
                price_min=min(fees) if fees else None,
                price_max=max(fees) if fees else None,
                is_free=(max(fees) == 0) if fees else None,
                default_categories=list(default_categories or []),
                raw={"race_id": race["race_id"], "event_types": sorted({ev.get("event_type") or "" for _, ev in same_day})},
            )
        )
    return out


class RunSignupSource(Source):
    def __init__(
        self,
        name: str,
        zipcode: str,
        *,
        radius: int = 15,
        days_ahead: int = 120,
        states: list[str] | None = None,
        exclude_patterns: list[str] | None = None,
        default_categories: list[str] | None = None,
        timeout: float = 45.0,
    ) -> None:
        self.name = name
        self.zipcode = str(zipcode)
        self.radius = radius
        self.days_ahead = days_ahead
        self.states = states or []
        self.exclude_patterns = exclude_patterns or []
        self.default_categories = default_categories or []
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        today = datetime.now(ZoneInfo(_DEFAULT_TZ)).date()
        races: list = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            for page in range(1, _MAX_PAGES + 1):
                resp = await client.get(
                    API_URL,
                    params={
                        "format": "json",
                        "zipcode": self.zipcode,
                        "radius": self.radius,
                        "start_date": today.isoformat(),
                        "end_date": (today + timedelta(days=self.days_ahead)).isoformat(),
                        "events": "T",
                        "sort": "date ASC",
                        "results_per_page": _PAGE_SIZE,
                        "page": page,
                    },
                )
                resp.raise_for_status()
                payload = resp.json()
                if not isinstance(payload, dict) or not isinstance(payload.get("races"), list):
                    raise ValueError(f"no 'races' list in the RunSignup response: {str(payload)[:200]}")
                races.extend(payload["races"])
                if len(payload["races"]) < _PAGE_SIZE:
                    break
        return parse_races(
            {"races": races},
            self.name,
            today=today,
            days_ahead=self.days_ahead,
            states=self.states,
            exclude_patterns=self.exclude_patterns,
            default_categories=self.default_categories,
        )
