"""Which local place a chat message names - a farm, a library, a venue with
events listed - worked out before the model sees it, like
services/chat_school_hint.py does for schools.

Asked "What's going on at Indian Acres?", the model took it for a school:
it looked one up, found none, and asked which school was meant (one run),
or found the farm only on its seventh tool call, on Sonnet (another), while
Indian Acres Tree Farm had its light trail in local events and on the
Christmas page. Saying so in the turn's context sends it straight there.
"""

import logging
from datetime import datetime, timedelta
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import or_, select

import database
from models import LocalEvent, ResourceService, SeasonalAttraction
from services.chat_school_hint import _GENERIC, _words, match_schools, town

logger = logging.getLogger(__name__)

ET = ZoneInfo("America/New_York")
_DAYS_AHEAD = 60
_MAX_LISTED = 3
# Words a place's name can start with that say where, not which place, and
# the ones that end a town or county's name ("Winslow Township").
_WHERE = _GENERIC | {"county", "township", "twp", "borough", "city", "nj", "pa"}
_JURISDICTION = ("county", "township", "twp", "borough")


def match_places(
    message: str, places: list[dict[str, Any]], schools: list[dict[str, Any]], named: list[dict[str, Any]] | None = None
) -> list[dict[str, Any]]:
    """The places the message names, longest match first: two or more of a
    place's first words, in order ("Indian Acres" for Indian Acres Tree
    Farm), and more than a town or county's name ("Cherry Hill" alone isn't
    Cherry Hill Mall, nor "Camden County" the Camden County Boathouse). A
    one-word name is left alone: "Holiday" would be Holiday Inn. So is one
    the school the message names already covers ("Bunker Hill" Middle isn't
    the Bunker Hill trails) - `named`, match_schools' answer if the caller
    has it already."""
    spoken = f" {' '.join(w for w in _words(message) if len(w) > 1)} "
    town_words = {w for s in schools for w in _words(town(s.get("address")))}
    if named is None:
        named = match_schools(message, schools)
    school_words = [set(_words(s.get("name"))) | set(_words(s.get("short_name"))) for s in named]
    found: list[tuple[int, dict]] = []
    for p in places:
        words = [w for w in _words(p["name"]) if len(w) > 1]
        if words[:1] == ["the"]:
            words = words[1:]
        n = next((k for k in range(len(words), 1, -1) if f" {' '.join(words[:k])} " in spoken), 0)
        said = words[:n]
        for w in _JURISDICTION:
            if w in said:
                said = said[said.index(w) + 1 :]
        if said and not set(said) <= town_words | _WHERE and not any(set(words[:n]) <= own for own in school_words):
            found.append((n, p))
    if not found:
        return []
    top = max(n for n, _ in found)
    return [p for n, p in found if n == top]


def place_hint(
    message: str, places: list[dict[str, Any]], schools: list[dict[str, Any]], named: list[dict[str, Any]] | None = None
) -> str | None:
    """A line for the turn's context naming the place(s) the message may mean, or None."""
    if named is None:
        named = match_schools(message, schools)
    found = match_places(message, places, schools, named)
    if not found or len(found) > _MAX_LISTED:
        return None

    def label(p: dict) -> str:
        where = f" in {p['town']}" if p.get("town") else ""
        lists = (["local events"] if p["events"] else []) + [f"the {s} seasonal attractions" for s in p["seasons"]]
        return f"{p['name']}{where} (in {' and '.join(lists)})"

    names = "; ".join(label(p) for p in found)
    search = "find_local_events with the place's name as `query`"
    if any(p["seasons"] for p in found):
        search += " and find_seasonal_attractions for its season"
    if named:
        return f"It may instead mean a local place: {names}. If so, search {search}."
    return (
        f"This message names a local place, not a tracked school: {names}. Before answering, search {search}; "
        "don't ask which school they mean."
    )


async def load_places() -> list[dict[str, Any]]:
    """Venues with local events in the next 60 days, and seasonal
    attractions' venues not yet over, or [] - a hint is never worth failing
    a turn over."""
    now = datetime.now(ET)
    try:
        async with database.SessionLocal() as db:
            venues = await db.scalars(
                select(LocalEvent.venue_name)
                .where(
                    LocalEvent.venue_name.is_not(None),
                    or_(LocalEvent.start_time >= now, LocalEvent.end_time > now),
                    LocalEvent.start_time < now + timedelta(days=_DAYS_AHEAD),
                    # A Localz provider's dates show only while its listing does
                    # (routers/local_events.py, _filters).
                    or_(
                        LocalEvent.resource_service_id.is_(None),
                        LocalEvent.resource_service_id.in_(select(ResourceService.id).where(ResourceService.status == "active")),
                    ),
                )
                .distinct()
            )
            attractions = (
                await db.execute(
                    select(SeasonalAttraction.venue, SeasonalAttraction.town, SeasonalAttraction.season).where(
                        SeasonalAttraction.venue.is_not(None), SeasonalAttraction.ends_on >= now.date()
                    )
                )
            ).all()
    except Exception:  # noqa: BLE001
        logger.warning("chatbot_place_list_failed", exc_info=True)
        return []
    places: dict[str, dict[str, Any]] = {}

    def place(name: str) -> dict[str, Any]:
        return places.setdefault(name.strip().lower(), {"name": name.strip(), "town": None, "events": False, "seasons": []})

    for name in venues:
        # An address for a venue ("615 Mercer Street, Cherry Hill") names no place.
        if name.strip() and not name.strip()[0].isdigit():
            place(name)["events"] = True
    for venue, where, season in attractions:
        p = place(venue)
        p["town"] = p["town"] or where
        p["seasons"] = sorted({*p["seasons"], season})
    return list(places.values())
