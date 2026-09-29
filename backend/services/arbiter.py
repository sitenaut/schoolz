"""ArbiterLive (arbiterlive.com) - the athletics-scheduling platform behind
`School.athletics_url` once that link is a `/m/team/<id>` page (some schools
still just link a generic site instead, see `entity_id_from_athletics_url`).
No auth, no bot-blocking of any kind (confirmed, unlike NJDOE's directory) -
a plain public JSON endpoint the page's own "Show calendar" button calls:

    GET /m/calendarmonth?entityId=<id>&year=<yyyy>&month=<m>

one month at a time, covering every sport/level at that school combined
(varsity and JV soccer, cross country, volleyball, ... all in one feed).
"""

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx

_BASE = "https://www.arbiterlive.com/m/calendarmonth"
_ET = ZoneInfo("America/New_York")
_TEAM_URL_RE = re.compile(r"arbiterlive\.com/m/team/(\d+)")
# Confirmed real (Cherry Hill East/West): the site's own "School Details"
# page links as "/Teams?entityId=<id>", not "/m/team/<id>" - both are real,
# fetchable ArbiterLive pages for the same entity id the calendar API
# takes, just two different URL shapes the site itself generates depending
# on which page you land on. Missing this silently meant East and West's
# `athletics_url` looked valid but never actually got a scan job created
# (_ensure_athletics_calendar_job only fires when this resolves).
_ENTITY_ID_QUERY_RE = re.compile(r"arbiterlive\.com/.*[?&]entityId=(\d+)")


def entity_id_from_athletics_url(athletics_url: str | None) -> str | None:
    """A school's athletics_url is a plain outbound link and isn't always
    ArbiterLive (some schools still link a generic athletics site, or a
    white-labeled ArbiterLive domain like easternvikings.arbiterwebsites.com
    this doesn't resolve) - only a real ArbiterLive team/entity URL has
    anything this module can fetch."""
    if not athletics_url:
        return None
    m = _TEAM_URL_RE.search(athletics_url) or _ENTITY_ID_QUERY_RE.search(athletics_url)
    return m.group(1) if m else None


def _months_between(start: date, end: date) -> list[tuple[int, int]]:
    months = []
    year, month = start.year, start.month
    while (year, month) <= (end.year, end.month):
        months.append((year, month))
        month += 1
        if month > 12:
            month = 1
            year += 1
    return months


def _parse_time(day: int, year: int, month: int, time_str: str | None) -> tuple[datetime, bool]:
    if not time_str:
        return datetime(year, month, day, tzinfo=_ET), True
    try:
        t = datetime.strptime(time_str.strip(), "%I:%M %p").time()
    except ValueError:
        return datetime(year, month, day, tzinfo=_ET), True
    return datetime.combine(date(year, month, day), t, tzinfo=_ET), False


async def fetch_events(entity_id: str, start: date, end: date, timeout: float = 30.0) -> list[dict]:
    """Returns a list of {external_uid, title, description, start_date,
    end_date, is_all_day} dicts - same shape as the other calendar sources
    in this app. One request per calendar month in [start, end]."""
    out: list[dict] = []
    async with httpx.AsyncClient(timeout=timeout) as client:
        for year, month in _months_between(start, end):
            resp = await client.get(_BASE, params={"entityId": entity_id, "year": year, "month": month}, headers={"Accept": "application/json"})
            resp.raise_for_status()
            payload = resp.json()

            for event in payload.get("events") or []:
                day = event.get("day")
                if not day:
                    continue
                start_dt, is_all_day = _parse_time(day, year, month, event.get("time"))
                if start_dt.date() < start or start_dt.date() > end:
                    continue

                game_id_match = re.search(r"/m/game/(\d+)", event.get("url") or "")
                game_id = game_id_match.group(1) if game_id_match else f"{year}{month:02d}{day:02d}-{event.get('title')}-{event.get('opponent')}"

                title = " ".join(part for part in (event.get("title"), event.get("opponent")) if part)
                out.append(
                    {
                        "external_uid": game_id,
                        "title": title or "(untitled)",
                        "description": event.get("location") or None,
                        "start_date": start_dt,
                        "end_date": None,
                        "is_all_day": is_all_day,
                    }
                )

    return out
