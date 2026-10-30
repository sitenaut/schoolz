"""DoStuff Media city guides (do215.com for Philadelphia; the same platform runs
do512, do206, ...).

Day pages (`/events/<category>/YYYY/MM/DD?page=N`) are a SvelteKit app, and
the data each one renders is served on its own at the same path plus
`/__data.json`, so plain httpx is enough - no scraper, no login. That JSON
carries title, venue name, start instant (with offset) and permalink, but no
description, price, ticket link, street address or coordinates (the venue's
`location` is null), so events are placed by venue name (`locate.py`).

  * The payload is devalue-encoded (`_devalue`): one flat array, every object
    and list holding indices into it. The rendered HTML is no substitute - its
    cards print "Tomorrow | 9 pm", and the site dropped its schema.org
    microdata in a redesign, which is what broke the old HTML adapter.
  * One request per day, paged (20 events a page, `_meta.has_next`). The
    category is a *path* segment (`live-music-events-philadelphia`): a
    `?category=music` query is silently ignored and returns the unfiltered
    day - walks, comedy, museum shows - so a wrong slug has to fail loudly
    (404), never quietly widen.
  * A show that started the night before is listed again on the next day
    (Built To Spill, Fri 8 pm, on Saturday's page). An event whose start
    isn't on the requested day is skipped, so each is kept once, on its own day.
  * The Philadelphia guide is the whole scope, so there is no radius filter.
  * Politeness: robots.txt allows /events but disallows map views.
    One pass per run, a pause between requests, a page cap per day.

Example job-params entry:

    {
      "name": "do215_music",
      "base_url": "https://do215.com",
      "category_path": "live-music-events-philadelphia",
      "days_ahead": 14,
      "default_categories": ["music", "philadelphia"]
    }
"""
from __future__ import annotations

import asyncio
import json
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from .base import RawEvent, Source

_ET = ZoneInfo("America/New_York")
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_PAUSE_SECONDS = 1.0
DEFAULT_DAYS_AHEAD = 14
DEFAULT_MAX_PAGES_PER_DAY = 4


def _devalue(values: list):
    """The value devalue's flat array encodes. Containers hold indices into
    the array; a negative index is one of its constants (undefined, NaN, ...),
    all None here; a list starting with a string is a tagged type (Date, Map,
    ...), kept as that list since nothing read here uses one."""
    memo: dict[int, object] = {}

    def at(i: int):
        if i < 0:
            return None
        if i in memo:
            return memo[i]
        v = values[i]
        if isinstance(v, dict):
            out: dict = {}
            memo[i] = out
            out.update((k, at(x)) for k, x in v.items())
            return out
        if isinstance(v, list) and not (v and isinstance(v[0], str)):
            items: list = []
            memo[i] = items
            items.extend(at(x) for x in v)
            return items
        return v

    return at(0)


def read_browse(text: str) -> dict:
    """The page's `browse` data: `data` (events grouped by date) and `_meta`
    (paging). Raises ValueError when there is none (a redesign or an error
    page), which is not the same as an empty day."""
    try:
        doc = json.loads(text)
    except ValueError:
        raise ValueError("DoStuff day data is not JSON - redesigned?") from None
    for node in (doc.get("nodes") if isinstance(doc, dict) else None) or []:
        if isinstance(node, dict) and node.get("type") == "data" and isinstance(node.get("data"), list):
            data = _devalue(node["data"])
            if isinstance(data, dict) and isinstance(data.get("browse"), dict):
                return data["browse"]
    raise ValueError("no DoStuff event data on the page - redesigned?")


def has_next(browse: dict) -> bool:
    return bool((browse.get("_meta") or {}).get("has_next"))


def parse_day(browse: dict, source: str, base_url: str, day: date, default_categories: list[str] | None = None) -> list[RawEvent]:
    """Events that start on `day`, from `read_browse`'s result."""
    out: list[RawEvent] = []
    for group in browse.get("data") or []:
        for ev in (group or {}).get("events") or []:
            if not isinstance(ev, dict) or ev.get("type") != "event":
                continue
            permalink, title = ev.get("permalink"), (ev.get("title") or "").strip()
            try:
                start = datetime.fromisoformat(ev.get("tz_adjusted_begin_time") or "")
            except ValueError:
                continue
            if not permalink or not title or start.tzinfo is None or start.astimezone(_ET).date() != day:
                continue
            try:
                end = datetime.fromisoformat(ev["tz_adjusted_end_time"]) if ev.get("tz_adjusted_end_time") else None
            except ValueError:
                end = None
            venue = ev.get("venue") or {}
            out.append(
                RawEvent(
                    source=source,
                    source_event_id=permalink,
                    title=title,
                    start_time=start,
                    end_time=end,
                    venue_name=(venue.get("title") or "").strip() or None,
                    # The page's own permalink is a stable landing page for the show.
                    url=f"{base_url.rstrip('/')}{permalink}",
                    image_url=ev.get("image_url") or None,
                    default_categories=list(default_categories or []),
                    raw={"genres": ev["genres"]} if ev.get("genres") else {},
                )
            )
    return out


class DoStuffSource(Source):
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        category_path: str = "live-music-events-philadelphia",
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        max_pages_per_day: int = DEFAULT_MAX_PAGES_PER_DAY,
        default_categories: list[str] | None = None,
        timeout: float = 30.0,
    ) -> None:
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.category_path = category_path.strip("/")
        self.days_ahead = max(1, days_ahead)
        self.max_pages_per_day = max(1, max_pages_per_day)
        self.default_categories = default_categories or []
        self.timeout = timeout
        self.partial_failures: list[str] = []

    def _url(self, day: date, page: int) -> str:
        query = f"?page={page}" if page > 1 else ""
        return f"{self.base_url}/events/{self.category_path}/{day:%Y/%m/%d}/__data.json{query}"

    async def fetch(self) -> list[RawEvent]:
        self.partial_failures = []
        events: dict[str, RawEvent] = {}
        today = datetime.now(_ET).date()
        days = [today + timedelta(days=i) for i in range(self.days_ahead)]
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            first = True
            for day in days:
                try:
                    for page in range(1, self.max_pages_per_day + 1):
                        if not first:
                            await asyncio.sleep(_PAUSE_SECONDS)
                        first = False
                        resp = await client.get(self._url(day, page))
                        resp.raise_for_status()
                        browse = read_browse(resp.text)
                        for ev in parse_day(browse, self.name, self.base_url, day, self.default_categories):
                            events.setdefault(ev.source_event_id, ev)
                        if not has_next(browse):
                            break
                except (httpx.HTTPError, ValueError) as exc:
                    self.partial_failures.append(f"{day.isoformat()}: {exc}")
        if len(self.partial_failures) == len(days):
            raise RuntimeError("every DoStuff day failed: " + "; ".join(self.partial_failures[:3]))
        return list(events.values())
