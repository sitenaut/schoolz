"""0142's soup kitchens: the API's checks, the same places on both season
pages, no name already seeded by 0138-0141, and no staff contact copied in
(the rows link to the volunteer page instead)."""
import importlib.util
import re
from pathlib import Path

from routers.seasonal_attractions import _validate, miles_between

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
CHERRY_HILL = (39.9268, -75.0246)
_CONTACT = re.compile(r"@|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")


def _migration(name: str):
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_soup_kitchens_pass_the_api_checks_on_both_seasons():
    earlier = {
        (row["season"], row["name"])
        for name in (
            "0138_thanksgiving_christmas_2026",
            "0139_volunteer_thanksgiving_christmas_2026",
            "0140_food_bank_volunteering",
            "0141_wreaths_washington_crossing",
        )
        for row in _migration(name)._ATTRACTIONS
    }
    rows = _migration("0142_soup_kitchens")._ATTRACTIONS
    names = {season: {r["name"] for r in rows if r["season"] == season} for season in ("fall", "winter")}
    assert names["fall"] and names["fall"] == names["winter"]
    assert len(rows) == len(names["fall"]) * 2
    for row in rows:
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["kind"] == "volunteer" and row["ages"]
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url"))
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50
        assert (row["season"], row["name"]) not in earlier
        assert not any(_CONTACT.search(row[k]) for k in ("schedule", "ages", "note"))
