"""0140's Food Bank of South Jersey rows: same checks as 0139's volunteer
rows, and no name already seeded for that season by 0138 or 0139."""
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


def test_food_bank_rows_pass_the_api_checks_and_say_who_can_come():
    earlier = {
        (row["season"], row["name"])
        for name in ("0138_thanksgiving_christmas_2026", "0139_volunteer_thanksgiving_christmas_2026")
        for row in _migration(name)._ATTRACTIONS
    }
    rows = _migration("0140_food_bank_volunteering")._ATTRACTIONS
    assert {row["season"] for row in rows} == {"fall", "winter"}
    for row in rows:
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["kind"] == "volunteer" and row["ages"]
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url"))
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50
        assert (row["season"], row["name"]) not in earlier
