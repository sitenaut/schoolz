import json
from datetime import date

import httpx
import pytest

from services import healthepro


def _setting(*items):
    return json.dumps({"current_display": [{"type": t, "name": n, "item": n} for t, n in items]})


LUNCH_DAY = _setting(
    ("category", "Lunch Entree"),
    ("recipe", "Chicken Nuggets"),
    ("recipe", "Cereal Variety, Yogurt & String Cheese"),
    ("category", "Vegetables"),
    ("recipe", "Baked Beans"),
    ("category", "Milk"),
    ("recipe", "1% Milk"),
)


def test_entrees_reads_only_recipes_under_an_entree_category():
    assert healthepro.entrees(LUNCH_DAY) == ["Chicken Nuggets", "Cereal Variety, Yogurt & String Cheese"]


def test_entrees_handles_breakfast_category_dedupes_and_bad_input():
    s = _setting(("category", "Breakfast Entree"), ("recipe", "Pancakes"), ("recipe", "Pancakes"))
    assert healthepro.entrees(s) == ["Pancakes"]
    assert healthepro.entrees(None) == []
    assert healthepro.entrees("not json") == []
    assert healthepro.entrees(json.dumps({"current_display": [{"type": "recipe", "name": "Orphan"}]})) == []


def test_pick_menus_skips_preschool_only_menus():
    menus = [
        {"id": 1, "meal_type_id": 1, "public_name": "Pre-k Breakfast Menu"},
        {"id": 2, "meal_type_id": 1, "public_name": "Breakfast After the Bell"},
        {"id": 3, "meal_type_id": 2, "public_name": "Pre-Lunch Menu"},
        {"id": 4, "meal_type_id": 2, "public_name": "Elementary Lunch Menu"},
        {"id": 5, "meal_type_id": 9, "public_name": "Snack"},
    ]
    chosen = healthepro.pick_menus(menus)
    assert {k: v["id"] for k, v in chosen.items()} == {"breakfast": 2, "lunch": 4}


def test_parse_location():
    assert healthepro.parse_location("2984/16222") == ("2984", "16222")
    assert healthepro.parse_location("3/297/1469") is None
    assert healthepro.parse_location("") is None


@pytest.mark.anyio
async def test_fetch_entrees_spans_months_and_tolerates_an_unpublished_one():
    def handler(request: httpx.Request) -> httpx.Response:
        path = request.url.path
        if path.endswith("/year/2026/month/10/date_overwrites"):
            return httpx.Response(200, json={"data": [
                {"day": "2026-10-30", "setting": LUNCH_DAY},
                {"day": "2026-10-15", "setting": LUNCH_DAY},  # before the window
                {"day": "bogus", "setting": LUNCH_DAY},
            ]})
        if path.endswith("/year/2026/month/11/date_overwrites"):
            return httpx.Response(200, json={"data": [{"day": "2026-11-02", "setting": LUNCH_DAY}]})
        return httpx.Response(404)

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await healthepro.fetch_entrees(client, "2984", 139778, date(2026, 10, 20), date(2026, 12, 1))
    assert sorted(out) == [date(2026, 10, 30), date(2026, 11, 2)]
    assert out[date(2026, 11, 2)][0] == "Chicken Nuggets"
