"""BiblioCommons library events via the public gateway API.

Burlington County Library System (bclsnj.bibliocommons.com) renders its
calendar client-side, but the page reads `gateway.bibliocommons.com/v2/
libraries/<slug>/events`, which needs no key. The response is normalized:
`events.items` lists ids and everything else is under `entities` (events,
locations, event types, audiences), merged here across pages.

`start`/`end` are local wall time; recurring events come back once per
occurrence (the id is per occurrence, `seriesId` ties them). Cancelled
occurrences are dropped. `branches` (names, case-insensitive) narrows a
system-wide feed to the libraries that serve tracked towns; omit it to keep all.

Example job-params entry:

    {
      "name": "burlington_county_library",
      "library": "bclsnj",
      "branches": ["Cinnaminson Library", "Evesham Library"],
      "default_categories": ["library"]
    }
"""
from __future__ import annotations

import html
import logging
import re
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
GATEWAY = "https://gateway.bibliocommons.com/v2/libraries"
PER_PAGE = 100
DEFAULT_DAYS_AHEAD = 90
DEFAULT_MAX_PAGES = 20
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_TAG_RE = re.compile(r"<[^>]+>")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(_TAG_RE.sub(" ", text)).replace("\xa0", " ")
    text = "\n".join(re.sub(r"[ \t]+", " ", line).strip() for line in text.splitlines())
    return re.sub(r"\n{3,}", "\n\n", text).strip() or None


def _local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value[:16]).replace(tzinfo=ET)
    except ValueError:
        return None


def _address(loc: dict) -> str | None:
    a = loc.get("address") or {}
    street = " ".join(p for p in (a.get("number"), a.get("street")) if p)
    parts = [street, a.get("city"), " ".join(p for p in (a.get("state"), a.get("zip")) if p)]
    return ", ".join(p for p in parts if p) or None


class BiblioCommonsSource(Source):
    def __init__(
        self,
        name: str,
        library: str,
        *,
        branches: list[str] | None = None,
        default_categories: list[str] | None = None,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        max_pages: int = DEFAULT_MAX_PAGES,
        timeout: float = 30.0,
    ):
        self.name = name
        self.library = library
        self.url = f"{GATEWAY}/{library}/events"
        self.branches = {b.strip().lower() for b in branches or [] if b.strip()}
        self.default_categories = default_categories or []
        self.days_ahead = days_ahead
        self.max_pages = max_pages
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        horizon = datetime.now(ET) + timedelta(days=self.days_ahead)
        events: dict[str, dict] = {}
        locations: dict[str, dict] = {}
        types: dict[str, dict] = {}
        order: list[str] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            for page in range(1, self.max_pages + 1):
                resp = await client.get(self.url, params={"page": page, "limit": PER_PAGE})
                resp.raise_for_status()
                body = resp.json()
                ents = body.get("entities") or {}
                events.update(ents.get("events") or {})
                locations.update(ents.get("locations") or {})
                types.update(ents.get("eventTypes") or {})
                ids = (body.get("events") or {}).get("items") or []
                order.extend(ids)
                pages = int(((body.get("events") or {}).get("pagination") or {}).get("pages") or 1)
                if not ids or page >= pages:
                    break
                last = _local(((events.get(ids[-1]) or {}).get("definition") or {}).get("start"))
                if last and last > horizon:
                    break

        out: list[RawEvent] = []
        for eid in order:
            e = events.get(eid) or {}
            d = e.get("definition") or {}
            start, title = _local(d.get("start")), _clean(d.get("title"))
            if not start or not title or start > horizon or d.get("isCancelled"):
                continue
            loc = locations.get(str(d.get("branchLocationId"))) or {}
            if self.branches and (loc.get("name") or "").lower() not in self.branches:
                continue
            room = _clean(d.get("locationDetails"))
            categories = list(self.default_categories)
            out.append(
                RawEvent(
                    source=self.name,
                    source_event_id=str(e.get("id") or eid),
                    title=title,
                    description=_clean(d.get("description")),
                    start_time=start,
                    end_time=_local(d.get("end")),
                    venue_name=loc.get("name"),
                    venue_address=", ".join(p for p in (room, _address(loc)) if p) or None,
                    url=f"https://{self.library}.bibliocommons.com/events/{e.get('id') or eid}",
                    default_categories=categories,
                    raw={
                        "series_id": e.get("seriesId"),
                        "types": [(types.get(t) or {}).get("name") for t in d.get("typeIds") or []],
                    },
                )
            )
        return out
