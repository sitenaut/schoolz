"""services/fdmealplanner.py against the real response shape: per-day rows,
each with an xmlMenuRecipes blob of <Details> items (trimmed from a real
Haddon Township Thomas Edison Elementary response)."""
from datetime import date

import httpx
import pytest

from services import fdmealplanner as fd

_XML = (
    '<MenuItems>'
    '<Details ComponentName="Taco Soft Chicken" ComponentEnglishName="Soft Tacos" IsEntreeType="1" MealType="Entree" />'
    '<Details ComponentName="Sandwich Crispy Chicken" ComponentEnglishName="Crispy Chicken Sandwich" IsEntreeType="1" MealType="Entree">'
    '<DietaryIconXml><Icon DietaryIcon=" " RecipeProductDietaryName="Low Fat" /></DietaryIconXml></Details>'
    '<Details ComponentName="PBJ" ComponentEnglishName="Peanut Butter &amp; Jelly Sandwich" IsEntreeType="1" MealType="Entree" />'
    '<Details ComponentName="Broccoli" ComponentEnglishName="Steamed Broccoli" IsEntreeType="0" MealType="Side" />'
    '<Details ComponentName="Milk 1%" ComponentEnglishName="1% Lowfat Milk" IsEntreeType="0" MealType=" Beverage" />'
    '<Details ComponentName="Taco Soft Chicken" ComponentEnglishName="Soft Tacos" IsEntreeType="1" MealType="Entree" />'
    '</MenuItems>'
)


def test_entrees_are_the_entree_items_in_order_deduped_and_unescaped():
    assert fd.entrees(_XML) == ["Soft Tacos", "Crispy Chicken Sandwich", "Peanut Butter & Jelly Sandwich"]


def test_entrees_tolerates_empty_or_broken_xml():
    assert fd.entrees(None) == []
    assert fd.entrees("<MenuItems><Details") == []


def test_standing_options_are_dropped_to_leave_the_days_entree():
    standing = ["Chicken Caesar Salad", "Bagel Lunch"]
    by_day = {
        date(2026, 9, 28): ["Soft Tacos", "Crispy Chicken Sandwich"] + standing,
        date(2026, 9, 29): ["Pretzel with Cheese Sauce"] + standing,
        date(2026, 9, 30): ["Crispy Popcorn Chicken"] + standing,
        date(2026, 10, 1): ["Cheese Pizza"] + standing,
        date(2026, 10, 2): standing,  # nothing rotating that day - show what there is
    }
    out = fd.day_descriptions(by_day)
    assert out[date(2026, 9, 28)] == "Soft Tacos, Crispy Chicken Sandwich"
    assert out[date(2026, 9, 29)] == "Pretzel with Cheese Sauce"
    assert out[date(2026, 10, 2)] == "Chicken Caesar Salad, Bagel Lunch"


def test_too_few_days_to_tell_standing_from_rotating_keeps_everything():
    by_day = {date(2026, 9, 28): ["Soft Tacos", "Bagel Lunch"], date(2026, 9, 29): ["Pizza", "Bagel Lunch"]}
    assert fd.day_descriptions(by_day)[date(2026, 9, 28)] == "Soft Tacos, Bagel Lunch"


def test_days_with_no_entrees_are_left_out():
    assert fd.day_descriptions({date(2026, 9, 28): []}) == {}


def test_parse_location():
    assert fd.parse_location("3/297/1469") == ("3", "297", "1469")
    assert fd.parse_location("297/1469") is None
    assert fd.parse_location("") is None


@pytest.mark.anyio
async def test_fetch_splits_a_window_across_months_and_keeps_only_window_days():
    seen = []

    def handler(request: httpx.Request) -> httpx.Response:
        p = request.url.params
        seen.append((p["monthId"], p["startDate"], p["endDate"], p["locationId"], p["mealPeriodId"]))
        rows = {
            "09": [{"strMenuForDate": "2026-09-29", "xmlMenuRecipes": _XML}, {"strMenuForDate": "2026-09-01", "xmlMenuRecipes": _XML}],
            "10": [{"strMenuForDate": "2026-10-01", "xmlMenuRecipes": _XML}],
        }[p["monthId"]]
        return httpx.Response(200, json={"result": rows})

    async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
        out = await fd.fetch_entrees(client, ("3", "297", "1472"), 2, date(2026, 9, 28), date(2026, 10, 16))

    assert seen == [("09", "2026/09/28", "2026/09/30", "1472", "2"), ("10", "2026/10/01", "2026/10/16", "1472", "2")]
    assert sorted(out) == [date(2026, 9, 29), date(2026, 10, 1)]  # 9/1 is outside the window
    assert out[date(2026, 10, 1)][0] == "Soft Tacos"
