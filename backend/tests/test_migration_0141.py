"""0141's Wreaths Across America row: the API's checks, one day on a
Saturday (Wreaths Across America Day always is), and no name already seeded
for that season by 0138, 0139 or 0140."""
import importlib.util
from pathlib import Path

from routers.seasonal_attractions import _validate, miles_between

_VERSIONS = Path(__file__).resolve().parent.parent / "alembic" / "versions"
CHERRY_HILL = (39.9268, -75.0246)


def _migration(name: str):
    spec = importlib.util.spec_from_file_location(name, _VERSIONS / f"{name}.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_wreaths_row_is_one_saturday_and_passes_the_api_checks():
    earlier = {
        (row["season"], row["name"])
        for name in (
            "0138_thanksgiving_christmas_2026",
            "0139_volunteer_thanksgiving_christmas_2026",
            "0140_food_bank_volunteering",
        )
        for row in _migration(name)._ATTRACTIONS
    }
    rows = _migration("0141_wreaths_washington_crossing")._ATTRACTIONS
    assert rows
    for row in rows:
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["season"] == "winter" and row["kind"] == "volunteer" and row["ages"]
        assert row["starts_on"] == row["ends_on"] and row["open_dates"] == [row["starts_on"]]
        assert row["starts_on"].weekday() == 5
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url"))
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50
        assert (row["season"], row["name"]) not in earlier
