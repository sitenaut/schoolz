"""GoBound (gobound.com, "Bound") - the athletics platform behind
`School.athletics_url` when that link is a school's calendar subscription feed:

    https://gobound.com/<state>/schools/<school-slug>/calendar/ical/<token>

The feed is the only way in. GoBound's own pages, its /api/ and
beta.gobound.com answer 403 to anything that isn't a browser (its robots.txt
says AI crawlers are blocked "at WAF level" too), so a school page can't be
read or searched. The feed is what GoBound builds for a family's calendar app,
and polling it is that use. The owner generates one per school on gobound.com:
the school's Calendar, the subscription icon, practices off, every activity but
School Events, Generate Calendar Link, Copy. A link can't be derived from
another school's, and none should be guessed.

One GET returns the school's whole calendar (Kingsway: 3.7k events over two
seasons), from CloudFront with REFRESH-INTERVAL P1D. Only competitions count:
a game's URL is /direct/comps/<id>/show, and /direct/noncomps/ is everything
else the school's facility calendar holds (practices, band rehearsals, youth
leagues, club meetings, "North Gym Closed"), dozens a day.

    SUMMARY:Girls Field Hockey: Jackson Township vs Kingsway Regional (Varsity)
    LOCATION:Kingsway Regional High School Anthony "Tony" Barchuk Stadium
    STATUS:CONFIRMED
    X-BND-ACTIVITYNAME:Girls Field Hockey
    X-BND-ACTIVITYLEVEL:Varsity

A game with no time yet is a VALUE=DATE with "(Time TBA)" in its title. A
called-off game is STATUS:CANCELLED, usually with "CANCELLED - " or
"POSTPONED - " already at the front of its title.
"""

import re
from datetime import date, datetime, time
from zoneinfo import ZoneInfo

import httpx
from icalendar import Calendar

SOURCE = "gobound"

_ET = ZoneInfo("America/New_York")
_FEED_RE = re.compile(
    r"^(?:https?|webcal)://(?:www\.)?gobound\.com/(?P<state>[a-z]{2})/schools/(?P<slug>[a-z0-9-]+)/calendar/ical/(?P<token>[a-z0-9]+)/?(?:[?#].*)?$",
    re.I,
)
_STATUS_PREFIX_RE = re.compile(r"^\s*(?:cancell?ed|postponed|rain(?:ed)?\s*out|suspended)\b", re.I)
_UNKNOWN_VENUE_RE = re.compile(r"^\s*TB[AD]\b", re.I)
# A high school's page carries its middle school's teams too, told apart by
# level ("7th Grade", "8th Grade", "Middle School", "MS Red") or by activity
# ("Cross Country (coed) (MS ONLY)"). "MS" counts only in capitals.
_MIDDLE_SCHOOL_TEAM_RE = re.compile(r"\bmiddle\s+school\b|\b[5-8](?:th)?\s+grade\b|\b[5-8](?:th)?\s*/\s*[6-8](?:th)?\b|(?-i:\bMS\b)", re.I)


def feed_url(athletics_url: str | None) -> str | None:
    """The https subscription feed an athletics_url names, or None for any
    other link (a school page, another vendor)."""
    m = _FEED_RE.match((athletics_url or "").strip())
    if not m:
        return None
    return f"https://gobound.com/{m['state'].lower()}/schools/{m['slug'].lower()}/calendar/ical/{m['token']}"


def school_key(athletics_url: str | None) -> tuple[str, str] | None:
    """(state, school slug) of a feed: two links to one school's calendar,
    made with different filters, are still the same school's games."""
    m = _FEED_RE.match((athletics_url or "").strip())
    return (m["state"].lower(), m["slug"].lower()) if m else None


def page_url(athletics_url: str | None) -> str | None:
    """The school's GoBound page, the link a parent follows: the feed itself
    is a calendar file, and the token is no use in a browser."""
    key = school_key(athletics_url)
    return f"https://gobound.com/{key[0]}/schools/{key[1]}" if key else None


def is_middle_school_team(event: dict) -> bool:
    """The team's level, read from its activity and level fields alone, never
    the title ("vs Kingsway Regional Middle School" is an opponent)."""
    return bool(_MIDDLE_SCHOOL_TEAM_RE.search(event.get("team") or ""))


def _text(component, name: str) -> str:
    return " ".join(str(component.get(name) or "").split())


def _when(value) -> tuple[datetime, bool]:
    if isinstance(value, datetime):
        return (value if value.tzinfo else value.replace(tzinfo=_ET)), False
    return datetime.combine(value, time.min, tzinfo=_ET), True


def parse_feed(body: bytes, start: date, end: date) -> list[dict]:
    """The competitions starting in [start, end], in the shape of
    services.arbiter.fetch_events ({external_uid, kind, team, title,
    description, start_date, end_date, is_all_day}). `team` is the activity
    and level ("Girls Field Hockey - MS Red"), for the middle-school split."""
    out: dict[str, dict] = {}
    for component in Calendar.from_ical(body).walk("VEVENT"):
        if "/direct/comps/" not in str(component.get("URL") or ""):
            continue
        uid, dtstart = str(component.get("UID") or "").strip(), component.get("DTSTART")
        if not uid or dtstart is None:
            continue
        start_dt, is_all_day = _when(dtstart.dt)
        if not start <= start_dt.astimezone(_ET).date() <= end:
            continue
        dtend = component.get("DTEND")
        title = _text(component, "SUMMARY") or "(untitled)"
        if str(component.get("STATUS") or "").upper() == "CANCELLED" and not _STATUS_PREFIX_RE.match(title):
            title = f"CANCELLED - {title}"
        venue = _text(component, "LOCATION")
        out[uid] = {
            "external_uid": f"gb:{uid}",
            "kind": "game",
            "team": " - ".join(part for part in (_text(component, "X-BND-ACTIVITYNAME"), _text(component, "X-BND-ACTIVITYLEVEL")) if part),
            "title": title[:300],
            "description": None if not venue or _UNKNOWN_VENUE_RE.match(venue) else venue,
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
    return parse_feed(resp.content, start, end)
