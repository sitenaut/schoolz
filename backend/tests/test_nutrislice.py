from datetime import date

import httpx
import pytest

from services import nutrislice


def _food(name, category):
    return {"food": {"name": name, "food_category": category}}


DAY = [
    {"is_station_header": True, "text": "Main Event", "food": None},
    _food("Everyday Favorites", ""),
    _food("Popcorn Chicken", "entree"),
    _food("Ham Cheese Sandwich", "entree"),
    _food("Popcorn Chicken", "entree"),
    _food("Whole Grain Dinner Roll", "grain"),
    _food("Vegetarian Baked Beans", "vegetable"),
]


def test_entrees_keeps_only_entree_foods_deduped():
    assert nutrislice.entrees(DAY) == ["Popcorn Chicken", "Ham Cheese Sandwich"]
    assert nutrislice.entrees(None) == []


def test_breakfast_without_an_entree_falls_back_to_grains():
    day = [_food("Double Chocolate Chip Muffin", "grain"), _food("Honey Graham Crackers", "grain"), _food("String Cheese Stick", "meat")]
    assert nutrislice.entrees(day, "breakfast") == ["Double Chocolate Chip Muffin", "Honey Graham Crackers"]
    assert nutrislice.entrees(day, "lunch") == []
    assert nutrislice.entrees(day + [_food("Fresh Whole Wheat Bagel", "entree")], "breakfast") == ["Fresh Whole Wheat Bagel"]


def test_uncategorized_tenant_takes_the_first_food():
    day = [_food("MOZZ STICKS, WG", ""), _food("Marinara Cup", ""), _food("MILK MIX - AVE", "")]
    assert nutrislice.entrees(day) == ["MOZZ STICKS, WG"]
    assert nutrislice.entrees(day, "breakfast") == ["MOZZ STICKS, WG"]
    # Breakfast files only some foods: an uncategorized lead item still wins,
    # a categorized one (grain) goes through the usual fallback.
    cereal = _food("Cereal Bowl - Cocoa Puffs", "other")
    assert nutrislice.entrees([_food("YOGURT-RASPBERRY DANIMAL", ""), cereal], "breakfast") == ["YOGURT-RASPBERRY DANIMAL"]
    assert nutrislice.entrees([_food("PUMPKIN BREAD", "grain"), cereal], "breakfast") == ["PUMPKIN BREAD"]


def test_parse_location():
    assert nutrislice.parse_location("cinnaminson/eleanor-rush-school") == ("cinnaminson", "eleanor-rush-school")
    assert nutrislice.parse_location("2984/16222/3") is None
    assert nutrislice.parse_location("") is None


def test_week_starts_covers_every_week_the_window_touches():
    # Wed Oct 7 .. Wed Oct 28 2026 touches four Sunday-to-Saturday weeks.
    assert nutrislice._week_starts(date(2026, 10, 7), date(2026, 10, 28)) == [
        date(2026, 10, 4), date(2026, 10, 11), date(2026, 10, 18), date(2026, 10, 25),
    ]
    assert nutrislice._week_starts(date(2026, 10, 4), date(2026, 10, 4)) == [date(2026, 10, 4)]


@pytest.mark.anyio
async def test_fetch_entrees_clips_to_window_and_tolerates_a_missing_meal():
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "cinnaminson.api.nutrislice.com"
        if "/menu-type/breakfast/" in request.url.path:
            return httpx.Response(404)
        if request.url.path.endswith("/2026/10/04/"):
            return httpx.Response(200, json={"days": [
                {"date": "2026-10-06", "menu_items": DAY},
                {"date": "2026-10-07", "menu_items": DAY},
                {"date": "2026-10-10", "menu_items": []},
            ]})
        return httpx.Response(200, json={"days": [{"date": "2026-10-12", "menu_items": [_food("Cheese Pizza", "entree")]}]})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        lunch = await nutrislice.fetch_entrees(client, "cinnaminson", "eleanor-rush-school", "lunch", date(2026, 10, 7), date(2026, 10, 12))
        breakfast = await nutrislice.fetch_entrees(client, "cinnaminson", "eleanor-rush-school", "breakfast", date(2026, 10, 7), date(2026, 10, 12))
    assert lunch == {date(2026, 10, 7): ["Popcorn Chicken", "Ham Cheese Sandwich"], date(2026, 10, 12): ["Cheese Pizza"]}
    assert breakfast == {}
