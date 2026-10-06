"""DoStuff Media city guides (do215.com for Philadelphia; the same platform runs
do512, do206, ...).

Day pages (`/events/<category>/YYYY/MM/DD?page=N`) server-render each event
as schema.org microdata, so plain httpx is enough - no scraper, no login. The
listing carries title, venue, street address, start instant (with offset) and
the ticket link, but no description, price or coordinates.

  * One request per day, paged (25 cards a page). The category is a *path*
    segment (`live-music-events-philadelphia`): a `?category=music` query is
    silently ignored and returns the unfiltered day - walks, comedy, museum
    shows - so a wrong slug has to fail loudly (404), never quietly widen.
  * A multi-day run ("Through Oct 09") is repeated on every day it spans with
    its *first* start date. A card whose start isn't on the requested day is
    skipped, so each event is kept once, on its own day.
  * Venues have no coordinates; the Philadelphia guide is the whole scope, so
    there is no radius filter.
  * Politeness: robots.txt allows /events but disallows search and map views.
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
import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

from .base import RawEvent, Source

_ET = ZoneInfo("America/New_York")
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_EVENT = '[itemtype="http://schema.org/Event"]'
_BG_URL_RE = re.compile(r"url\(['\"]?([^'\")]+)")
_PAUSE_SECONDS = 1.0
DEFAULT_DAYS_AHEAD = 14
DEFAULT_MAX_PAGES_PER_DAY = 4


def _meta(node, prop: str) -> str | None:
    el = node.select_one(f'meta[itemprop="{prop}"]')
    return (el.get("content") or "").strip() or None if el else None


def _start(card) -> datetime | None:
    raw = _meta(card, "startDate")
    if not raw:
        return None
    try:
        # "2026-10-09T20:30-0400": the offset has no colon, which 3.10's
        # fromisoformat rejects.
        return datetime.strptime(raw, "%Y-%m-%dT%H:%M%z")
    except ValueError:
        try:
            return datetime.fromisoformat(raw)
        except ValueError:
            return None


def parse_day(page_html: str, source: str, base_url: str, day: date, default_categories: list[str] | None = None) -> list[RawEvent]:
    """Events that start on `day`. Raises ValueError when the page has no
    event-list markup at all (a redesign), which is not the same as an empty day."""
    soup = BeautifulSoup(page_html, "html.parser")
    if not soup.select_one(".ds-listing, .ds-events-group, #ds-content") and not soup.select(_EVENT):
        raise ValueError("no DoStuff event markup on the page - redesigned?")
    out: list[RawEvent] = []
    for card in soup.select(_EVENT):
        permalink = card.get("data-permalink")
        title_el = card.select_one('[itemprop="name"]')
        start = _start(card)
        if not permalink or not title_el or not start:
            continue
        if start.astimezone(_ET).date() != day:
            continue
        venue_el = card.select_one('[itemprop="location"] [itemprop="name"]')
        street, city = _meta(card, "streetAddress"), _meta(card, "addressLocality")
        region, zip_code = _meta(card, "addressRegion"), _meta(card, "postalCode")
        locality = ", ".join(p for p in (city, " ".join(p for p in (region, zip_code) if p)) if p)
        # Some venues type the whole address into streetAddress already.
        full = street if street and ((zip_code and zip_code in street) or (city and city.lower() in street.lower())) else None
        address = full or ", ".join(p for p in (street, locality) if p) or None
        ticket_el = card.select_one('[itemprop="offers"] meta[itemprop="url"]')
        cover = card.select_one(".ds-cover-image")
        image = _BG_URL_RE.search(cover.get("style", "")) if cover else None
        out.append(
            RawEvent(
                source=source,
                source_event_id=permalink,
                title=title_el.get_text(" ", strip=True),
                start_time=start,
                venue_name=venue_el.get_text(" ", strip=True) if venue_el else None,
                venue_address=address,
                # The page's own permalink is a stable landing page for the show;
                # the ticket link is an affiliate-tagged third-party URL.
                url=f"{base_url.rstrip('/')}{permalink}",
                image_url=image.group(1) if image else None,
                default_categories=list(default_categories or []),
                raw={"ticket_url": ticket_el.get("content")} if ticket_el else {},
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
        return f"{self.base_url}/events/{self.category_path}/{day:%Y/%m/%d}{query}"

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
                        got = parse_day(resp.text, self.name, self.base_url, day, self.default_categories)
                        for ev in got:
                            events.setdefault(ev.source_event_id, ev)
                        # The page marks another one with rel="next".
                        if 'rel="next"' not in resp.text:
                            break
                except (httpx.HTTPError, ValueError) as exc:
                    self.partial_failures.append(f"{day.isoformat()}: {exc}")
        if len(self.partial_failures) == len(days):
            raise RuntimeError("every DoStuff day failed: " + "; ".join(self.partial_failures[:3]))
        return list(events.values())
