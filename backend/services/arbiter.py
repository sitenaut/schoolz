"""ArbiterLive (arbiterlive.com) - the athletics-scheduling platform behind
`School.athletics_url` once that link is a `/m/team/<id>` page (some schools
still just link a generic site instead, see `entity_id_from_athletics_url`).
No auth, no bot-blocking of any kind (confirmed, unlike NJDOE's directory) -
a plain public JSON endpoint the page's own "Show calendar" button calls:

    GET /m/calendarmonth?entityId=<id>&year=<yyyy>&month=<m>

one month at a time, covering every sport/level at that school combined
(varsity and JV soccer, cross country, volleyball, ... all in one feed).
"""

import html
import json
import re
from datetime import date, datetime
from zoneinfo import ZoneInfo

import httpx

# Sources of game schedules (dozens a week), hidden from the general calendar
# and day cards unless asked for. DigitalSports' is services/digitalsports.SOURCE.
ATHLETICS_SOURCES = ("arbiter_athletics", "digitalsports")

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
# Confirmed real (Audubon HS, found via its white-labeled audubonathletics.com
# site's own "Calendar" link): a third real shape, "/School/Calendar/<id>" -
# same entity id the calendar API takes, just yet another page the
# ArbiterLive site itself generates depending on the current UI/entry point.
_SCHOOL_CALENDAR_URL_RE = re.compile(r"arbiterlive\.com/School/(?:Calendar/)?(\d+)")


def entity_id_from_athletics_url(athletics_url: str | None) -> str | None:
    """A school's athletics_url is a plain outbound link and isn't always
    ArbiterLive (some schools still link a generic athletics site, or a
    white-labeled ArbiterLive domain like easternvikings.arbiterwebsites.com
    or audubonathletics.com this doesn't resolve directly - the real
    arbiterlive.com entity link has to be found on *that* site instead) -
    only a real ArbiterLive team/entity URL has anything this module can
    fetch. Bordentown High links the bare /School/<id> form."""
    if not athletics_url:
        return None
    m = (
        _TEAM_URL_RE.search(athletics_url)
        or _ENTITY_ID_QUERY_RE.search(athletics_url)
        or _SCHOOL_CALENDAR_URL_RE.search(athletics_url)
    )
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

                # A game is /m/game/<id>; Gateway's school events (field trips,
                # Financial Aid Night) are /m/event/<id> on the same calendar,
                # which Arbiter is rolling out as a school's own event calendar.
                url_match = re.search(r"/m/(game|event)/(\d+)", event.get("url") or "")
                kind = url_match.group(1) if url_match else "game"
                if url_match:
                    game_id = url_match.group(2) if kind == "game" else f"event:{url_match.group(2)}"
                else:
                    game_id = f"{year}{month:02d}{day:02d}-{event.get('title')}-{event.get('opponent')}"

                # The JSON carries HTML entities ("Baking &amp; Builders Club").
                title = html.unescape(" ".join(part for part in (event.get("title"), event.get("opponent")) if part))
                location = html.unescape(event.get("location") or "")
                out.append(
                    {
                        "external_uid": game_id,
                        "kind": kind,
                        "team": event.get("title") or "",
                        "title": title or "(untitled)",
                        "description": location or None,
                        "start_date": start_dt,
                        "end_date": None,
                        "is_all_day": is_all_day,
                    }
                )

    return out


_STATUS_RE = re.compile(r'class="calPopOverGameStatus[^"]*">\s*([^<]+?)\s*</span>', re.I)
_GAME_URL_RE = re.compile(r"/Teams/Game/(\d+)")
_EVENT_URL_RE = re.compile(r"uniqueEventId=(\d+)")


async def fetch_statuses(entity_id: str, start: date, end: date, timeout: float = 30.0) -> dict[str, str]:
    """{external_uid: status} for the games and events a school's calendar page
    marks "Canceled", "Postponed" or "Rainout". The calendarmonth feed our
    scan reads has no status field at all, so a cancelled game looked like any
    other; the school calendar page (/School/Calendar/<id>) loads its own feed,
    /School/GetEventsByEntity/, whose titles carry the status in a badge. That
    feed takes its entity from the page visit's session, hence the GET first.
    A status is a nicety, so any failure returns {} and never fails the scan."""
    try:
        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": "schoolz-athletics/1.0"}) as client:
            await client.get(f"https://www.arbiterlive.com/School/Calendar/{entity_id}")
            resp = await client.post(
                "https://www.arbiterlive.com/School/GetEventsByEntity/",
                data={"startDate": f"{start.year}-{start.month}-{start.day}", "endDate": f"{end.year}-{end.month}-{end.day}"},
                headers={"X-Requested-With": "XMLHttpRequest"},
            )
            resp.raise_for_status()
            items = json.loads(resp.json()["EventsFilteredDetailString"])
    except (httpx.HTTPError, ValueError, KeyError, TypeError):
        return {}
    out: dict[str, str] = {}
    for item in items:
        status = _STATUS_RE.search(item.get("title") or "")
        if not status:
            continue
        url = item.get("url") or ""
        game, event = _GAME_URL_RE.search(url), _EVENT_URL_RE.search(url)
        if game:
            out[game.group(1)] = status.group(1)
        elif event:
            out[f"event:{event.group(1)}"] = status.group(1)
    return out


# Delsea's high-school entity also names them "Basketball - Boys 7/8th".
_MIDDLE_SCHOOL_TEAM_RE = re.compile(r"\bmiddle school\s*$|\b7(?:th)?\s*/\s*8(?:th)?\s*$", re.I)


def is_middle_school_team(event: dict) -> bool:
    """The team's level, read from the team name alone ("Field Hockey - Girls
    Middle School"), never the opponent ("vs Northern Burlington Middle
    School")."""
    return bool(_MIDDLE_SCHOOL_TEAM_RE.search(event.get("team") or ""))


def games_for_school(school_type: str | None, own: list[dict], sibling_high_school: list[dict], district_has_middle_school: bool) -> list[dict]:
    """Which games a school shows when one district's teams are split across
    Arbiter entities. Pennsauken's high-school entity also carries most of
    Phifer Middle's teams, and Phifer's own entity only a few: a middle school
    adds the middle-school teams from its district's high-school entities,
    and a high school whose district has a middle school leaves them out."""
    if school_type == "middle":
        games = {e["external_uid"]: e for e in own}
        for e in sibling_high_school:
            if is_middle_school_team(e):
                games.setdefault(e["external_uid"], e)
        return list(games.values())
    if school_type == "high" and district_has_middle_school:
        return [e for e in own if not is_middle_school_team(e)]
    return own
