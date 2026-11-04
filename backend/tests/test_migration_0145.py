"""0145's Localz listings for the season pages' volunteer places: complete
records that pass the portal's own checks, categories the app would give
them, general contacts only, and a listing decision for every volunteer
place any migration seeds, so a new one can't skip it."""
import importlib.util
from pathlib import Path

from resources.categories import categories_for
from resources.portal import WaysToHelp, clean_ways_to_help
from resources.provider_types import BY_CODE
from routers.seasonal_attractions import miles_between

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
CHERRY_HILL = (39.9268, -75.0246)
_GENERAL_MAILBOXES = {"info", "access", "gethelp"}


def _migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _migration(_VERSIONS / "0145_volunteer_places_on_localz.py")


def test_listings_are_complete_and_pass_the_portal_checks():
    keys = [row["source_record_id"] for row in M._LISTINGS]
    assert len(keys) == len(set(keys))
    for row in M._LISTINGS:
        assert M.missing_core(row) == [], row["source_record_id"]
        codes = [M._TYPES[t][0] for t in row["types"]]
        assert all(c in BY_CODE or c == "PH-2950.3200" for c in codes)
        assert M.categories(row["types"]) == categories_for(codes, row["name"], row["description"])
        assert row["website"].startswith("https://")
        assert row["email"] is None or row["email"].split("@")[0] in _GENERAL_MAILBOXES
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50
        assert row["service_areas"] and len(row["description"]) <= 500
        # What the provider portal would store for the same input, unchanged.
        assert clean_ways_to_help(WaysToHelp(**row["ways_to_help"])) == row["ways_to_help"]
    for ways in [*M._NJ211_HELP.values(), M._TOYS_FOR_TOTS_HELP]:
        assert clean_ways_to_help(WaysToHelp(**ways)) == ways


def test_every_card_points_at_a_listing_this_migration_fills():
    listing_keys = {row["source_record_id"] for row in M._LISTINGS}
    for target in M._CARD_LISTINGS.values():
        assert target in M._NJ211_HELP if isinstance(target, tuple) else target in listing_keys
    assert not set(M._CARD_LISTINGS) & set(M._NO_LISTING)


def test_every_volunteer_place_has_a_listing_decision():
    """A migration that seeds a volunteer place says, in its own
    _CARD_LISTINGS or _NO_LISTING, which listing it gets or why none."""
    places, decided = set(), set()
    for path in sorted(_VERSIONS.glob("0*.py")):
        text = path.read_text()
        if "_ATTRACTIONS" not in text and "_CARD_LISTINGS" not in text:
            continue
        module = _migration(path)
        places |= {row["name"] for row in getattr(module, "_ATTRACTIONS", []) if row.get("kind") == "volunteer"}
        decided |= set(getattr(module, "_CARD_LISTINGS", {})) | set(getattr(module, "_NO_LISTING", {}))
    assert places and places <= decided, sorted(places - decided)


def test_the_toys_for_tots_guide_starts_after_the_pages_other_guides():
    (season, _title, _publisher, url, note, starts, ends, order), = M._GUIDES
    assert season == "winter" and url.startswith("https://") and starts <= ends and order > 55 and len(note) < 300
