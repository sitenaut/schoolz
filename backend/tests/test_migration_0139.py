"""0139's holiday volunteering seed: every row it would insert passes the
API's own checks, sits within 50 miles of Cherry Hill, says how young a
volunteer can be, and doesn't collide with a 0138 name in the same season."""
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


def test_volunteer_rows_pass_the_api_checks_and_say_who_can_come():
    m = _migration("0139_volunteer_thanksgiving_christmas_2026")
    earlier = {(row["season"], row["name"]) for row in _migration("0138_thanksgiving_christmas_2026")._ATTRACTIONS}
    seen = set()
    for row in m._ATTRACTIONS:
        name = row["name"]
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["season"] in {"fall", "winter"}, name
        # The season page's "Volunteer & give back" heading (KIND_LABELS in frontend/src/lib/seasonal.ts).
        assert row["kind"] == "volunteer", name
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("url", "ticket_url", "source_url")), name
        assert row["url"] and row["address"] and row["town"], name
        assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50, name
        # Families read this list for whether their kids can come.
        assert row["ages"], f"{name}: no age rule"
        if row["starts_on"] == row["ends_on"]:
            assert row["open_dates"] == [row["starts_on"]], f"{name}: a one-day event says which day"
        assert (row["season"], name) not in seen, f"{name} twice"
        assert (row["season"], name) not in earlier, f"{name} is already in 0138"
        seen.add((row["season"], name))


def test_guides_have_sane_windows_and_no_repeats():
    m = _migration("0139_volunteer_thanksgiving_christmas_2026")
    seen = set()
    for season, title, publisher, url, _note, starts, ends, order in m._GUIDES:
        assert season in {"fall", "winter"}, title
        assert url.startswith("https://") and publisher, title
        assert starts <= ends, title
        # Behind 0138's guides, so the season's banner headline stays theirs.
        assert order >= 50, title
        assert (season, url) not in seen, f"{title} twice"
        seen.add((season, url))
