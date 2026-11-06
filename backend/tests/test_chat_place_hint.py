import uuid
from datetime import date, datetime, timedelta
from zoneinfo import ZoneInfo

import pytest

import database
from models import LocalEvent, SeasonalAttraction
from services.chat_place_hint import load_places, match_places, place_hint

pytestmark = pytest.mark.anyio

SCHOOLS = [
    {"slug": "pine-acres", "name": "Pine Acres Early Childhood Center", "short_name": "Pine Acres", "address": "720 Purdue Ave, Wenonah, NJ 08090"},
    {"slug": "beck", "name": "Henry C. Beck Middle School", "short_name": "Beck", "address": "950 Cropwell Rd, Cherry Hill, NJ 08003"},
]


def _p(name, town=None, events=True, seasons=()):
    return {"name": name, "town": town, "events": events, "seasons": list(seasons)}


PLACES = [
    _p("Indian Acres Tree Farm", "Medford", seasons=["winter"]),
    _p("Cherry Hill Mall"),
    _p("Camden County Library - Voorhees"),
    _p("Camden County Boathouse"),
    _p("Johnson's Corner Farm", "Medford", events=False, seasons=["winter"]),
    _p("Time"),
    _p("The Fillmore Philadelphia"),
]


def _names(message):
    return [p["name"] for p in match_places(message, PLACES, SCHOOLS)]


def test_the_first_words_of_a_place_name_it():
    assert _names("What's going on at Indian Acres?") == ["Indian Acres Tree Farm"]
    assert _names("whats going on at indian acres") == ["Indian Acres Tree Farm"]
    assert _names("Breakfast with Santa at Johnson's Corner Farm?") == ["Johnson's Corner Farm"]
    assert _names("Who's playing at the Fillmore Philadelphia?") == ["The Fillmore Philadelphia"]


def test_a_town_or_a_word_alone_names_no_place():
    assert _names("Is there school tomorrow in Cherry Hill?") == []
    assert _names("Anything at the Cherry Hill Mall for kids?") == ["Cherry Hill Mall"]
    assert _names("Any events in Camden County this weekend?") == []
    assert _names("Is the Camden County Boathouse open?") == ["Camden County Boathouse"]
    assert _names("What time does school end?") == []


def test_the_hint_says_search_events_and_seasons():
    hint = place_hint("What's going on at Indian Acres?", PLACES, SCHOOLS)
    assert "Indian Acres Tree Farm in Medford (in local events and the winter seasonal attractions)" in hint
    assert "find_local_events" in hint and "find_seasonal_attractions" in hint and "don't ask which school" in hint
    also = place_hint("What's going on at Indian Acres?", PLACES, SCHOOLS, named=[SCHOOLS[0]])
    assert also.startswith("It may instead mean a local place") and "don't ask" not in also
    assert place_hint("Is Beck closed tomorrow?", PLACES, SCHOOLS) is None


def test_a_place_the_named_school_covers_is_that_school():
    places = [_p("Bunker Hill Trails"), _p("Beck Middle School")]
    schools = [*SCHOOLS, {"slug": "bunker-hill", "name": "Bunker Hill Middle School", "short_name": "Bunker Hill", "address": "1 Main St, Sewell, NJ 08080"}]
    assert match_places("Is Bunker Hill Middle School closed tomorrow?", places, schools) == []
    assert match_places("Is there a concert at Beck Middle School?", places, schools) == []
    assert [p["name"] for p in match_places("Are the Bunker Hill Trails open?", places, schools)] == ["Bunker Hill Trails"]


async def test_places_are_upcoming_event_venues_and_seasonal_venues():
    tag = uuid.uuid4().hex[:8]
    soon = datetime.now(ZoneInfo("America/New_York")) + timedelta(days=3)

    def event(venue, start=soon):
        return LocalEvent(source=f"hint_{tag}", source_event_id=uuid.uuid4().hex, title="Lights", categories=[], start_time=start, venue_name=venue)

    async with database.SessionLocal() as db:
        db.add_all([
            event(f"Orchard {tag} Farm"),
            event(f"Orchard {tag} Farm"),
            event(f"Past {tag} Hall", soon - timedelta(days=30)),
            event(f"Far {tag} Hall", soon + timedelta(days=90)),
            event(f"12 Main Street {tag}, Medford"),
        ])
        db.add(SeasonalAttraction(
            season="winter", kind="light_show", name="Light Trail", venue=f"Orchard {tag} Farm", address="1 Main St, Medford, NJ",
            town="Medford", url="https://example.org", starts_on=date.today(), ends_on=date.today() + timedelta(days=30),
        ))
        await db.commit()
    places = {p["name"]: p for p in await load_places() if tag in p["name"]}
    assert places == {f"Orchard {tag} Farm": {"name": f"Orchard {tag} Farm", "town": "Medford", "events": True, "seasons": ["winter"]}}
