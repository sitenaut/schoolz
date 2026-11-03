"""GoBound (gobound.com, "Bound") - the athletics and activities platform behind
`School.athletics_url` when that link is a calendar subscription feed:

    https://gobound.com/<state>/schools/<school-slug>/calendar/ical/<token>
    https://gobound.com/<state>/conferences/<slug>/calendar/ical/<token>#<Team>|<Alias>

The feed is the only way in. GoBound's own pages, its /api/ and
beta.gobound.com answer 403 to anything that isn't a browser (its robots.txt
says AI crawlers are blocked "at WAF level" too), so a school page can't be
read or searched. The feed is what GoBound builds for a family's calendar app,
and polling it is that use. The owner generates one per school on gobound.com:
the school's Calendar, the subscription icon, practices off, every activity but
School Events, Generate Calendar Link, Copy. A link can't be derived from
another school's, and none should be guessed.

One GET returns the school's whole calendar (Kingsway: 3.7k events over two
seasons), from CloudFront with REFRESH-INTERVAL P1D. A game's URL is
/direct/comps/<id>/show. /direct/noncomps/ is everything else on the school's
calendar: practices, band and play rehearsals, club meetings, class trips and
dances, but also the facility bookings of outside groups (Washington Township's
"WTPR Youth Soccer", a church on Sundays), with nothing in the feed to tell the
two apart. The owner wants all of them, so they are kept as kind "event".

    SUMMARY:Girls Field Hockey: Jackson Township vs Kingsway Regional (Varsity)
    LOCATION:Kingsway Regional High School Anthony "Tony" Barchuk Stadium
    STATUS:CONFIRMED
    X-BND-ACTIVITYNAME:Girls Field Hockey
    X-BND-ACTIVITYLEVEL:Varsity

A game with no time yet is a VALUE=DATE with "(Time TBA)" in its title. A
called-off game is STATUS:CANCELLED, usually with "CANCELLED - " or
"POSTPONED - " already at the front of its title.

A conference's feed (Tri-County Conference, Burlington County Scholastic League)
lists its member schools' league games and nothing else, for schools with no
page of their own (Highland, Deptford). It has no level field, so the level is
read from the title's parentheses, and a school's games are the ones with one
of the team names after the link's "#" on either side of "vs": the feed spells
one school more than one way ("Deptford", "Deptford High School").
"""

import re
from datetime import date, datetime, time
from urllib.parse import unquote
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

SOURCE = "gobound"
# Non-game events of a school whose GoBound calendar is its events calendar
# (School.arbiter_events_calendar: Williamstown's dances, class trips and
# ceremonies), shown like any school event. Everywhere else they are
# practices, rehearsals and facility bookings, dozens a day, so they are filed
# under SOURCE with the games, behind the calendar's sports toggle.
EVENTS_SOURCE = "gobound_events"

_ET = ZoneInfo("America/New_York")
_FEED_RE = re.compile(
    r"^(?:https?|webcal)://(?:www\.)?gobound\.com/(?P<state>[a-z]{2})/(?P<kind>schools|conferences)/(?P<slug>[a-z0-9-]+)"
    r"/calendar/ical/(?P<token>[a-z0-9]+)/?(?:\?[^#]*)?(?:#(?P<teams>.*))?$",
    re.I,
)
_STATUS_PREFIX_RE = re.compile(r"^\s*(?:cancell?ed|postponed|rain(?:ed)?\s*out|suspended)\b", re.I)
_STATUS_DASH_RE = re.compile(r"^\s*(?:cancell?ed|postponed|rain(?:ed)?\s*out|suspended)\s*-\s*", re.I)
_UNKNOWN_VENUE_RE = re.compile(r"^\s*TB[AD]\b", re.I)
_PARENS_RE = re.compile(r"\(([^)]*)\)")
# A high school's page carries its middle school's teams too, told apart by
# level ("7th Grade", "8th Grade", "Middle School", "MS Red") or by activity
# ("Cross Country (coed) (MS ONLY)"). "MS" counts only in capitals.
_MIDDLE_SCHOOL_TEAM_RE = re.compile(r"\bmiddle\s+school\b|\b[5-8](?:th)?\s+grade\b|\b[5-8](?:th)?\s*/\s*[6-8](?:th)?\b|(?-i:\bMS\b)", re.I)
_MIDDLE_SCHOOL_VENUE_RE = re.compile(r"\bmiddle\s+school\b", re.I)


def _match(athletics_url: str | None):
    return _FEED_RE.match((athletics_url or "").strip())


def feed_url(athletics_url: str | None) -> str | None:
    """The https subscription feed an athletics_url names, or None for any
    other link (a school page, another vendor). The team names after "#" stay
    behind: they say which games are ours, and are never sent."""
    m = _match(athletics_url)
    if not m:
        return None
    return f"https://gobound.com/{m['state'].lower()}/{m['kind'].lower()}/{m['slug'].lower()}/calendar/ical/{m['token']}"


def team_names(athletics_url: str | None) -> tuple[str, ...]:
    """The team names a conference link keeps, "|"-separated after its "#"."""
    m = _match(athletics_url)
    if not m or not m["teams"]:
        return ()
    return tuple(name for name in (" ".join(part.split()) for part in unquote(m["teams"]).split("|")) if name)


def school_key(athletics_url: str | None) -> tuple[str, str, str, tuple[str, ...]] | None:
    """(state, kind, slug, team names) of a feed: two links to one school's
    calendar, made with different filters, are still the same school's games."""
    m = _match(athletics_url)
    if not m:
        return None
    return (m["state"].lower(), m["kind"].lower(), m["slug"].lower(), tuple(sorted(n.lower() for n in team_names(athletics_url))))


def page_url(athletics_url: str | None) -> str | None:
    """The school's (or conference's) GoBound page, the link a parent follows:
    the feed itself is a calendar file, and the token is no use in a browser."""
    key = school_key(athletics_url)
    return f"https://gobound.com/{key[0]}/{key[1]}/{key[2]}" if key else None


def is_middle_school_team(event: dict) -> bool:
    """The team's level, read from its activity and level fields alone, never
    the title ("vs Kingsway Regional Middle School" is an opponent)."""
    return bool(_MIDDLE_SCHOOL_TEAM_RE.search(event.get("team") or ""))


def is_middle_school_item(event: dict) -> bool:
    """A game by its team's level; any other event by where it happens
    ("Kingsway Regional Middle School West Gym"), since a rehearsal or a room
    booking has no level."""
    if event.get("kind") == "event":
        return bool(_MIDDLE_SCHOOL_VENUE_RE.search(event.get("location") or ""))
    return is_middle_school_team(event)


def _text(component, name: str) -> str:
    return " ".join(str(component.get(name) or "").split())


def _when(value) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=_ET)), False
    return datetime.combine(value, time.min, tzinfo=_ET), True


def _sides(title: str) -> list[str]:
    """The teams a game's title names ("Girls Soccer: Glassboro vs Penns Grove
    (Varsity)"), levels dropped and joint teams ("Clayton/Glassboro") split."""
    body = _STATUS_DASH_RE.sub("", title).split(":", 1)[-1]
    sides = []
    for side in re.split(r"\s+vs\.?\s+", body):
        side = _PARENS_RE.sub(" ", side)
        sides += [" ".join(part.split()).lower() for part in side.split("/")]
    return [side for side in sides if side]


def parse_feed(body: bytes, start: date, end: date, teams: tuple[str, ...] = ()) -> list[dict]:
    """The events starting in [start, end], in the shape of
    services.arbiter.fetch_events ({external_uid, kind, team, title,
    description, start_date, end_date, is_all_day}), plus `location`. A game is
    kind "game", anything else "event". `team` is the activity and level
    ("Girls Field Hockey - MS Red"), for the middle-school split. With `teams`
    (a conference feed) only the games those teams play are kept."""
    wanted = {" ".join(t.split()).lower() for t in teams}
    out: dict[str, dict] = {}
    for component in Calendar.from_ical(body).walk("VEVENT"):
        kind = "game" if "/direct/comps/" in str(component.get("URL") or "") else "event"
        uid, dtstart = str(component.get("UID") or "").strip(), component.get("DTSTART")
        title = _text(component, "SUMMARY")
        if not uid or dtstart is None or (kind == "event" and not title):
            continue
        if wanted and (kind != "game" or not wanted.intersection(_sides(title))):
            continue
        start_dt, is_all_day = _when(dtstart.dt)
        if not start <= start_dt.astimezone(_ET).date() <= end:
            continue
        dtend = component.get("DTEND")
        title = title or "(untitled)"
        if str(component.get("STATUS") or "").upper() == "CANCELLED" and not _STATUS_PREFIX_RE.match(title):
            title = f"CANCELLED - {title}"
        venue = _text(component, "LOCATION")
        # A conference feed has no level field; its titles carry the level.
        level = _text(component, "X-BND-ACTIVITYLEVEL") or " ".join(_PARENS_RE.findall(title.split(":", 1)[-1]))
        out[uid] = {
            "external_uid": f"gb:{uid}",
            "kind": kind,
            "team": " - ".join(part for part in (_text(component, "X-BND-ACTIVITYNAME"), level) if part),
            "title": title[:300],
            "description": None if not venue or _UNKNOWN_VENUE_RE.match(venue) else venue,
            "location": venue,
            "start_date": start_dt,
            "end_date": _when(dtend.dt)[0] if dtend is not None and not is_all_day else None,
            "is_all_day": is_all_day,
        }
    return list(out.values())


async def fetch_events(url: str, start: date, end: date, timeout: float = 60.0) -> list[dict]:
    """One GET of the whole feed (a couple of MB), then parse_feed."""
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers={"User-Agent": "schoolz-athletics/1.0"}) as client:
        resp = await client.get(feed_url(url) or url)
        resp.raise_for_status()
    return parse_feed(resp.content, start, end, team_names(url))
