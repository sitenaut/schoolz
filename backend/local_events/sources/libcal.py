"""Springshare LibCal public calendars via their own JSON list endpoint.

Libraries host these at `<name>.libcal.com` or a custom domain
(events.moorestownlibrary.org). The public page loads its list from
`/ajax/calendar/list`, which needs no key and no calendar id: `c=-1` is "all
calendars" and `date=0000-00-00` means "from today on", paged by `perpage`/
`page`. That beats `ical_subscribe.php`, whose `cid` has to be dug out of the
page and changes if the library reshuffles its calendars.

Recurring events come back once per occurrence under the same `id`, so the
source event id is `<id>:<start>`. `startdt`/`enddt` are local wall time.

Example job-params entry:

    {
      "name": "moorestown_library",
      "base_url": "https://events.moorestownlibrary.org",
      "venue_name": "Moorestown Library",
      "venue_address": "111 West Second Street, Moorestown, NJ 08057",
      "default_categories": ["moorestown", "library"]
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
PER_PAGE = 50
DEFAULT_DAYS_AHEAD = 90
DEFAULT_MAX_PAGES = 20
_UA = "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126 Safari/537.36"
_TAG_RE = re.compile(r"<[^>]+>")
_WS_RE = re.compile(r"[ \t\r\f\v]+")


def _clean(text: str | None) -> str | None:
    if not text:
        return None
    text = html.unescape(_TAG_RE.sub(" ", text)).replace("\xa0", " ")
    text = "\n".join(_WS_RE.sub(" ", line).strip() for line in text.splitlines())
    text = re.sub(r"\n{3,}", "\n\n", text).strip()
    return text or None


def _local(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.strptime(value, "%Y-%m-%d %H:%M:%S").replace(tzinfo=ET)
    except ValueError:
        return None


class LibCalSource(Source):
    def __init__(
        self,
        name: str,
        base_url: str,
        *,
        venue_name: str | None = None,
        venue_address: str | None = None,
        default_categories: list[str] | None = None,
        days_ahead: int = DEFAULT_DAYS_AHEAD,
        max_pages: int = DEFAULT_MAX_PAGES,
        timeout: float = 30.0,
    ):
        self.name = name
        self.base_url = base_url.rstrip("/")
        self.url = f"{self.base_url}/ajax/calendar/list"
        self.venue_name = venue_name
        self.venue_address = venue_address
        self.default_categories = default_categories or []
        self.days_ahead = days_ahead
        self.max_pages = max_pages
        self.timeout = timeout

    async def fetch(self) -> list[RawEvent]:
        now = datetime.now(ET)
        today = now.replace(hour=0, minute=0, second=0, microsecond=0)
        horizon = now + timedelta(days=self.days_ahead)
        rows: list[dict] = []
        async with httpx.AsyncClient(timeout=self.timeout, follow_redirects=True, headers={"User-Agent": _UA}) as client:
            for page in range(1, self.max_pages + 1):
                resp = await client.get(
                    self.url,
                    params={
                        "c": -1, "date": "0000-00-00", "perpage": PER_PAGE, "page": page,
                        "audience": "", "cats": "", "camps": "", "inc": 0,
                    },
                )
                resp.raise_for_status()
                body = resp.json()
                batch = body.get("results") or []
                rows.extend(batch)
                if not batch or len(rows) >= int(body.get("total_results") or 0):
                    break
                # Results are date-ordered: once a page ends past the horizon, stop.
                last = _local(batch[-1].get("startdt"))
                if last and last > horizon:
                    break

        out: list[RawEvent] = []
        for row in rows:
            start = _local(row.get("startdt"))
            title = _clean(row.get("title"))
            end = _local(row.get("enddt"))
            # The endpoint still lists multi-day events that began before today;
            # drop only the ones already over.
            if not start or not title or start > horizon or (end or start) < today:
                continue
            all_day = bool(row.get("all_day"))
            location = _clean(row.get("location"))
            out.append(
                RawEvent(
                    source=self.name,
                    source_event_id=f"{row.get('id')}:{row.get('startdt')}",
                    title=title,
                    description=_clean(row.get("description")) or _clean(row.get("shortdesc")),
                    start_time=start,
                    end_time=end,
                    all_day=all_day,
                    venue_name=self.venue_name,
                    # The room goes in the address line so the library stays the venue.
                    venue_address=", ".join(p for p in (location, self.venue_address) if p) or None,
                    url=row.get("url") or None,
                    image_url=row.get("featured_image") or None,
                    default_categories=list(self.default_categories),
                    raw={"libcal_id": row.get("id"), "audiences": [a.get("name") for a in row.get("audiences") or []]},
                )
            )
        return out
