"""0143's gift drives and Operation Santa link: the API's checks, nothing
already seeded by 0138-0142, no staff contact copied in, and a Christmas
guide that neither starts before that page's other guides nor takes its
banner headline."""
import importlib.util
import re
from datetime import date
from pathlib import Path

from routers.seasonal_attractions import _validate, miles_between

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
CHERRY_HILL = (39.9268, -75.0246)
_CONTACT = re.compile(r"@|\(?\b\d{3}\)?[-. ]\d{3}[-. ]\d{4}\b")
_EARLIER = (
    "0138_thanksgiving_christmas_2026",
    "0139_volunteer_thanksgiving_christmas_2026",
    "0140_food_bank_volunteering",
    "0141_wreaths_washington_crossing",
    "0142_soup_kitchens",
)


def _migration(name: str):
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_gift_drives_pass_the_api_checks():
    earlier = {(row["season"], row["name"]) for name in _EARLIER for row in _migration(name)._ATTRACTIONS}
    rows = _migration("0143_adopt_a_family")._ATTRACTIONS
    assert {row["season"] for row in rows} == {"fall", "winter"}
    for row in rows:
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["kind"] == "volunteer" and row["ages"] and row["price"]
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url"))
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50
        assert (row["season"], row["name"]) not in earlier
        assert not any(_CONTACT.search(row[k]) for k in ("schedule", "price", "ages", "note"))


def test_operation_santa_is_a_christmas_link_inside_the_season():
    earlier = {
        (g[0], g[3])
        for name in ("0138_thanksgiving_christmas_2026", "0139_volunteer_thanksgiving_christmas_2026")
        for g in _migration(name)._GUIDES
    }
    guides = _migration("0143_adopt_a_family")._GUIDES
    assert guides
    for season, title, publisher, url, note, starts, ends, order in guides:
        assert season == "winter" and title and publisher and note and url.startswith("https://")
        assert date(2026, 11, 13) <= starts <= ends
        assert order >= 50
        assert (season, url) not in earlier
