"""0148's toy drive card and Localz listing: the API's and the portal's own
checks, no position for a drive given to by mail, nothing already seeded,
and general contacts only."""
import importlib.util
import re
from pathlib import Path

from resources.categories import categories_for
from resources.portal import WaysToHelp, clean_ways_to_help
from routers.seasonal_attractions import _validate

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
_CONTACT = re.compile(r"@|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")


def _migration(path: Path):
    spec = importlib.util.spec_from_file_location(path.stem, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


M = _migration(_VERSIONS / "0148_we_cant_to_we_can_toy_drive.py")


def test_cards_pass_the_api_checks_and_are_new():
    earlier = set()
    for path in sorted(_VERSIONS.glob("01[34]*.py")):
        if path.stem < "0148" and "_ATTRACTIONS" in path.read_text():
            earlier |= {(row["season"], row["name"]) for row in _migration(path)._ATTRACTIONS}
    assert {row["season"] for row in M._ATTRACTIONS} == {"fall", "winter"}
    for row in M._ATTRACTIONS:
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["kind"] == "volunteer" and row["ages"] and row["price"] and row["address"] and row["town"]
        # Given by mail or online: nowhere to go, so no Directions.
        assert row["latitude"] is None and row["longitude"] is None
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url"))
        assert (row["season"], row["name"]) not in earlier
        assert not any(_CONTACT.search(row[k]) for k in ("schedule", "price", "ages", "note"))
    assert set(M._CARD_LISTINGS) == {M._NAME} and M._CARD_LISTINGS[M._NAME] == M._LISTING_KEY


def test_the_listing_passes_the_portal_checks():
    row = M._LISTING
    codes = [M._TYPES[t][0] for t in row["types"]]
    assert M.missing_core(row) == []
    assert M.categories(row["types"]) == categories_for(codes, row["name"], row["description"])
    assert row["website"].startswith("https://") and len(row["description"]) <= 500
    # Its flyer's name, so a Localz search for it finds the listing.
    assert "Give a Toy, Make a Christmas" in row["description"]
    assert row["email"].split("@")[0] == "contact"
    # A P.O. box only: nothing to map.
    assert not any(row[k] for k in ("address", "city", "postal_code", "latitude", "longitude"))
    assert clean_ways_to_help(WaysToHelp(**row["ways_to_help"])) == row["ways_to_help"]
