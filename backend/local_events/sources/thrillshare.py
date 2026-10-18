"""Town sites built on Apptegy (Thrillshare) - Mount Ephraim, Oaklyn borough.

Same public events API the school calendars use (services/apptegy.py), keyed
by the site's numeric org id. The id is read off the town page's own network
calls (`thrillshare.com/api/v4/o/<org>/cms/events`); there's no lookup. A
town org is not its school district's org (Oaklyn borough is 25480, Oaklyn
Public School 4847).

`live_feed` also reads the site's Live Feed posts (`cms/live_feeds`). Oaklyn
announces its picnic, movie nights and Green Day there, never on the
calendar - mixed in with gas-main work schedules, spraying notices and
agendas. Each post goes through the event-page reader (event_pages.py),
which skips the notices; a post's text is read once ever (page_extractions).
A post that moves or cancels an event takes back the date an earlier post
gave. A post's images are transcribed first (flyers.py), so a flyer posted
under a bare title is read too.
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

import httpx

from services import apptegy

from .base import RawEvent, Source
from .event_pages import EventPageSource, Post, read_posts
from .theatre import page_text

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


class ThrillshareSource(Source):
    def __init__(
        self,
        name: str,
        org_id: str,
        site_url: str | None = None,
        days_ahead: int = 90,
        default_categories: list[str] | None = None,
        live_feed: bool = False,
        live_feed_days: int = 45,
        location: str | None = None,
    ):
        self.name = name
        self.org_id = str(org_id)
        self.site_url = site_url
        self.url = f"https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/{self.org_id}/cms/events"
        self.days_ahead = days_ahead
        self.default_categories = default_categories or []
        self.live_feed = live_feed
        self.live_feed_days = live_feed_days
        self.location = location
        self.partial_failures = []

    async def fetch(self) -> list[RawEvent]:
        self.partial_failures = []
        calendar = await self._calendar()
        if not self.live_feed:
            return calendar
        try:
            posted = await self._live_feed()
        except Exception as exc:  # noqa: BLE001 - the calendar still counts
            self.partial_failures.append(f"live feed: {type(exc).__name__}: {exc}"[:200])
            posted = []
        return calendar + posted

    async def _live_feed(self) -> list[RawEvent]:
        now = datetime.now(_ET)
        cutoff = now - timedelta(days=self.live_feed_days)
        posts: list[dict] = []
        url = f"https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/{self.org_id}/cms/live_feeds"
        async with httpx.AsyncClient(timeout=30) as client:
            for page in range(1, 6):
                resp = await client.get(url, params={"page_no": page})
                resp.raise_for_status()
                batch = resp.json().get("live_feeds") or []
                posts += batch
                if not batch or datetime.fromisoformat(batch[-1]["time"]) < cutoff:
                    break
        reader = EventPageSource(name=self.name, urls=[self.site_url or url], town=self.location)
        feed_url = (self.site_url or "").rstrip("/") + "/live-feed" if self.site_url else None
        kept = [
            Post(
                ref=str(p.get("id")),
                posted=datetime.fromisoformat(p["time"]),
                body=page_text(p.get("status") or "", self.site_url or ""),
                url=feed_url or url,
                images=[i["url"] for i in p.get("live_feed_images") or [] if isinstance(i, dict) and i.get("url")],
            )
            for p in posts
            if datetime.fromisoformat(p["time"]) >= cutoff
        ]
        return await read_posts(
            reader, kept, default_categories=list(self.default_categories), id_prefix="post",
            today=now.date(), failures=self.partial_failures,
        )

    async def _calendar(self) -> list[RawEvent]:
        today = datetime.now(_ET).date()
        events = await apptegy.fetch_events(self.org_id, today, today + timedelta(days=self.days_ahead))
        return [
            RawEvent(
                source=self.name,
                source_event_id=event["external_uid"],
                title=event["title"],
                description=event["description"],
                start_time=event["start_date"],
                end_time=event["end_date"],
                all_day=event["is_all_day"],
                venue_name=event.get("venue"),
                venue_address=event.get("venue"),
                latitude=event.get("latitude"),
                longitude=event.get("longitude"),
                url=self.site_url,
                default_categories=list(self.default_categories),
            )
            for event in events
        ]
