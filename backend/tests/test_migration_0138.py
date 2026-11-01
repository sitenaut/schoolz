"""0138's Thanksgiving and Christmas seed: every row it would insert passes
the API's own checks, sits within 50 miles of Cherry Hill, and has a kind
the season page gives a heading."""
import importlib.util
from pathlib import Path

from routers.seasonal_attractions import _validate, miles_between

_PATH = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0138_thanksgiving_christmas_2026.py"
CHERRY_HILL = (39.9268, -75.0246)
# Each has a heading in frontend/src/lib/seasonal.ts (KIND_LABELS).
KINDS = {"turkey_trot", "race", "parade", "farm", "light_show", "santa", "train", "market", "tree_lighting", "ice_rink", "festival"}


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0138", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_attractions_pass_the_api_checks_and_stay_within_50_miles():
    m = _migration()
    seen = set()
    for row in m._ATTRACTIONS:
        name = row["name"]
        _validate(row["starts_on"], row["ends_on"], row["open_dates"], row.get("scare_level"))
        assert row["season"] in {"fall", "winter"}, name
        assert row["kind"] in KINDS, name
        assert row["url"].startswith("https://"), name
        assert all(row.get(k) is None or row[k].startswith("https://") for k in ("ticket_url", "source_url")), name
        assert row["address"] and row["town"], name
        # No geocoder places DiDonato's in Hammonton (about 25 miles), so its
        # Directions link works from the address alone.
        if row["latitude"] is not None or name != "Magical Holiday Express":
            assert miles_between(*CHERRY_HILL, row["latitude"], row["longitude"]) <= 50, name
        if row["kind"] in {"turkey_trot", "parade", "tree_lighting"}:
            assert row["open_dates"], f"{name}: a one-day event says which day"
        assert (row["season"], name) not in seen, f"{name} twice"
        seen.add((row["season"], name))


def test_guides_have_sane_windows_and_no_repeats():
    m = _migration()
    seen = set()
    for season, title, publisher, url, _note, starts, ends, _order in m._GUIDES:
        assert season in {"fall", "winter"}, title
        assert url.startswith("https://") and publisher, title
        assert starts <= ends, title
        assert (season, url) not in seen, f"{title} twice"
        seen.add((season, url))
