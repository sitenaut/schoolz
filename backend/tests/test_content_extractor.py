from services.content_extractor import _parse_lunch_menu_days

# Confirmed real shape from a Chesterbrook Academy Smore lunch-menu flyer:
# the model's own description text for a category="lunch_menu" item.
_REAL_DESCRIPTION = (
    "September lunch menu for Chesterbrook Academy of Voorhees. "
    "Monday 7: School Closed. "
    "Monday 14: Chicken Patty Sandwich with veggie & fruit, AM Oatmeal Bar, PM Veggie Straws. "
    "Tuesday 1: Baked Ziti w/ Meat Sauce with veggie & fruit, AM Cereal & Milk, PM Cinnamon Grams. "
    "Friday 25: Cheese Pizza with veggie & fruit, AM Oatmeal Bar, PM Cheese-Its. "
    "Available daily: Water, Milk, Fresh Fruits, Fresh Vegetables."
)


def test_parses_every_day_entry():
    days = _parse_lunch_menu_days(_REAL_DESCRIPTION, year=2026, month=9)
    assert len(days) == 4
    assert {d["date"].day for d in days} == {7, 14, 1, 25}


def test_trailing_available_daily_note_is_stripped_not_glued_to_last_day():
    days = _parse_lunch_menu_days(_REAL_DESCRIPTION, year=2026, month=9)
    last = max(days, key=lambda d: d["date"])
    assert "Available daily" not in last["description"]
    assert last["description"] == "Cheese Pizza with veggie & fruit, AM Oatmeal Bar, PM Cheese-Its"


def test_leading_title_text_before_first_day_is_ignored():
    days = _parse_lunch_menu_days(_REAL_DESCRIPTION, year=2026, month=9)
    assert not any("September lunch menu" in d["description"] for d in days)


def test_no_day_markers_returns_empty_list():
    assert _parse_lunch_menu_days("Just a paragraph with no day markers.", year=2026, month=9) == []
