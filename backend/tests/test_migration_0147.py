"""0147's light trail passes the API's own checks, sits within 50 miles of
Cherry Hill, and isn't already in 0138."""
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


def test_the_light_trail_passes_the_api_checks():
    earlier = {(row["season"], row["name"]) for row in _migration("0138_thanksgiving_christmas_2026")._ATTRACTIONS}
    for row in _migration("0147_indian_acres_light_trail")._ATTRACTIONS:
        name = row["name"]
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["open_dates"] == sorted(set(row["open_dates"])), name
        assert row["starts_on"] == row["open_dates"][0] and row["ends_on"] == row["open_dates"][-1], name
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url")), name
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50, name
        assert (row["season"], name) not in earlier, f"{name} is already in 0138"
