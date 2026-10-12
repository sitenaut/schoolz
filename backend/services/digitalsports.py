"""DigitalSports (`<school>.digitalsports.com`, "Powered by VantageSportz") - the
athletics-scheduling platform behind `School.athletics_url` when that link is a
`<host>.digitalsports.com` site (Wood-Ridge; the North Jersey Interscholastic
Conference's schools). No auth, no bot wall, server-rendered, plain httpx.

The schedule page (`/pages/schedule/schedule.php`) pages by week: its arrows
call

    GET /pages/schedule/call-school-ajax.php?filter=bydate&date=YYYY-MM-DD

which returns that date and the six days after it as one `<h2>` per day and a
`.schedule-table` of rows. That HTML is what the site shows, so it is the source
here, not the FullCalendar feed (`schedule-json.php`, a POST that takes Unix
`start`/`end`): the feed still lists the originals of rescheduled games, and
omits some games the page shows.

Row shape:
    <td><strong>4:00 PM</strong></td>
    <td><a href='javascript:showEventDetailsNew(7483894);'>Soccer: Boys Junior Varsity Game</a>
        <span class="add-event-info">(Rescheduled from 10-28-26)</span></td>
    <td><span class="opponent">vs X High School</span> @ <a>Venue</a></td>
An away game has no `.opponent` class: `<span class='theme-color'> @ X</span> @ <a>Venue</a>`.
"""

import re
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import httpx
from bs4 import BeautifulSoup

SOURCE = "digitalsports"

_ET = ZoneInfo("America/New_York")
_HOST_RE = re.compile(r"^https?://([a-z0-9-]+)\.digitalsports\.com(?:[/?#]|$)", re.I)
_PATH = "/pages/schedule/call-school-ajax.php"
_EVENT_ID_RE = re.compile(r"showEventDetailsNew\((\d+)\)")
_DAY_RE = re.compile(r"([A-Za-z]+)\s+(\d{1,2})(?:st|nd|rd|th)\s+(\d{4})")
# "Soccer: Boys Junior Varsity Game" -> sport, team, what it is.
_TITLE_RE = re.compile(r"^(?P<sport>[^:]+):\s*(?P<team>.+?)\s+(?P<kind>Game|Scrimmage|Practice|Tournament|Match|Meet)$", re.I)


def host_from_athletics_url(athletics_url: str | None) -> str | None:
    """The `<school>.digitalsports.com` subdomain, or None for any other link.
    Only a school's own site has a schedule to read; the bare digitalsports.com
    is the vendor's."""
    m = _HOST_RE.match((athletics_url or "").strip())
    if not m or m.group(1).lower() in ("www", "leagueminder"):
        return None
    return m.group(1).lower()


def _week_starts(start: date, end: date) -> list[date]:
    """Mondays covering [start, end]. The endpoint returns the given date plus
    six days, so stepping by 7 from a Monday tiles the range with no overlap."""
    day = start - timedelta(days=start.weekday())
    out = []
    while day <= end:
        out.append(day)
        day += timedelta(days=7)
    return out


def _parse_day(text: str) -> date | None:
    m = _DAY_RE.search(text)
    if not m:
        return None
    try:
        return datetime.strptime(f"{m.group(1)} {m.group(2)} {m.group(3)}", "%B %d %Y").date()
    except ValueError:
        return None


def _start(day: date, time_text: str) -> tuple[datetime, bool]:
    try:
        t = datetime.strptime(time_text.strip().upper(), "%I:%M %p").time()
    except ValueError:
        return datetime(day.year, day.month, day.day, tzinfo=_ET), True
    return datetime.combine(day, t, tzinfo=_ET), False


def parse_week(html: str) -> list[dict]:
    """Events of one weekly page, in the same shape as services.arbiter.fetch_events
    ({external_uid, kind, team, title, description, start_date, end_date,
    is_all_day}). `kind` is "game" for everything with a team, "event" for a
    school event with none. Practices are dropped: they are the team's
    business, and dozens a week."""
    soup = BeautifulSoup(html, "html.parser")
    out: list[dict] = []
    for heading in soup.find_all("h2"):
        day = _parse_day(heading.get_text(" ", strip=True))
        table = heading.find_next_sibling("table")
        if not day or not table:
            continue
        for row in table.select("tbody tr"):
            cells = row.find_all("td")
            link = row.find("a", href=_EVENT_ID_RE)
            if len(cells) < 3 or not link:
                continue
            event_id = _EVENT_ID_RE.search(link["href"]).group(1)
            name = " ".join(link.get_text(" ", strip=True).split())
            m = _TITLE_RE.match(name)
            kind_word = m.group("kind").title() if m else None
            if kind_word == "Practice":
                continue
            notes = [" ".join(s.get_text(" ", strip=True).split()) for s in cells[1].select(".add-event-info")]
            # An "away" opponent is a bare theme-color span; a home one is .opponent.
            details = cells[2]
            opp_span = details.select_one("span.opponent") or details.find("span", class_="theme-color")
            opponent = " ".join(opp_span.get_text(" ", strip=True).split()) if opp_span else ""
            venue_link = details.find("a", onclick=re.compile(r"details\.php"))
            venue = " ".join(venue_link.get_text(" ", strip=True).split()) if venue_link else ""
            if venue.upper() in ("TBD", "TBA"):
                venue = ""
            # A school event has no team: its name is the cell's text ahead of the venue.
            if venue_link:
                venue_link.extract()
            cell_text = " ".join(details.get_text(" ", strip=True).split()).rstrip("@ ").strip()
            start_dt, is_all_day = _start(day, cells[0].get_text(" ", strip=True))

            if m:
                team = f"{m.group('sport').strip()} - {m.group('team').strip()}"
                title = f"{team} {opponent}".strip()
                if kind_word != "Game":
                    title += f" ({kind_word})"
                kind = "game"
            else:
                team, title, kind = "", cell_text or name.strip() or "(untitled)", "event"
            # Notes like "Game" or "Season" only repeat the title; keep the
            # informative ones ("Rescheduled from", "Senior Night", a tournament).
            keep = [n for n in notes if n.lower() not in ("game", "season", "season game", "season games", "match")]
            description = " - ".join(part for part in ([venue] + keep) if part) or None
            out.append(
                {
                    "external_uid": f"ds:{event_id}",
                    "kind": kind,
                    "team": team,
                    "title": title,
                    "description": description,
                    "start_date": start_dt,
                    "end_date": None,
                    "is_all_day": is_all_day,
                }
            )
    return out


async def fetch_events(host: str, start: date, end: date, timeout: float = 30.0) -> list[dict]:
    """Every event in [start, end], one request per week. A week that fails
    (one 5xx) is skipped rather than failing the scan, unless every week fails -
    then the site is down and the scan should say so."""
    out: dict[str, dict] = {}
    failures = 0
    weeks = _week_starts(start, end)
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": "schoolz-athletics/1.0"}) as client:
        for monday in weeks:
            try:
                resp = await client.get(f"https://{host}.digitalsports.com{_PATH}", params={"filter": "bydate", "date": monday.isoformat()})
                resp.raise_for_status()
            except httpx.HTTPError:
                failures += 1
                continue
            for event in parse_week(resp.text):
                if start <= event["start_date"].date() <= end:
                    out[event["external_uid"]] = event
    if weeks and failures == len(weeks):
        raise httpx.HTTPError(f"{host}.digitalsports.com: every weekly schedule request failed")
    return list(out.values())
