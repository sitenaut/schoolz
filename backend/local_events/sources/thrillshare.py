"""Town sites built on Apptegy (Thrillshare) - Mount Ephraim, Oaklyn borough.

Same public events API the school calendars use (services/apptegy.py), keyed
by the site's numeric org id. The id is read off the town page's own network
calls (`thrillshare.com/api/v4/o/<org>/cms/events`); there's no lookup. A
town org is not its school district's org (Oaklyn borough is 25480, Oaklyn
Public School 4847).
"""
from __future__ import annotations

from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from services import apptegy

from .base import RawEvent, Source

_ET = ZoneInfo("America/New_York")


class ThrillshareSource(Source):
    def __init__(
        self,
        name: str,
        org_id: str,
        site_url: str | None = None,
        days_ahead: int = 90,
        default_categories: list[str] | None = None,
    ):
        self.name = name
        self.org_id = str(org_id)
        self.site_url = site_url
        self.url = f"https://thrillshare-cmsv2.services.thrillshare.com/api/v4/o/{self.org_id}/cms/events"
        self.days_ahead = days_ahead
        self.default_categories = default_categories or []
        self.partial_failures = []

    async def fetch(self) -> list[RawEvent]:
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
