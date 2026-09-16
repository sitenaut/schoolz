from datetime import datetime
from zoneinfo import ZoneInfo

from models import SchoolContentItem
from services.content_extractor import (
    _add_years,
    _backfill_from_duplicate,
    _correct_stale_year,
    _infer_lunch_menu_start_date,
    _may_supersede,
    _parse_lunch_menu_days,
)

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


# Confirmed real shape from the actual Chesterbrook Academy prod extraction
# that motivated this fix: month/day grouped by weekday, only the first
# entry of each weekday group repeats the weekday word, and the day is
# written as "M/D" (redundantly including the already-known month) rather
# than a bare day number.
_MD_GROUPED_DESCRIPTION = (
    "Monday 9/1: Baked Ziti w/ Meat Sauce, Veggie & Fruit (AM: Cereal & Milk, PM: Cinnamon Grams); "
    "9/8: Pasta w/ Marinara Sauce, Veggie & Fruit (AM: Cereal & Milk, PM: Cinnamon Grams); "
    "9/15: Baked Ziti, Veggie, Fruit (AM: Cereal & Milk, PM: Cinnamon Grams). "
    "Tuesday 9/2: Tacos, Veggie, Fruit (AM: Bagels w/ Cream Cheese, PM: Pretzels)."
)


def test_parses_month_slash_day_entries_with_weekday_only_on_first_of_group():
    days = _parse_lunch_menu_days(_MD_GROUPED_DESCRIPTION, year=2026, month=9)
    assert {d["date"].day for d in days} == {1, 8, 15, 2}
    first = next(d for d in days if d["date"].day == 1)
    assert first["description"] == "Baked Ziti w/ Meat Sauce, Veggie & Fruit (AM: Cereal & Milk, PM: Cinnamon Grams)"


def test_bare_weekday_dd_format_still_works():
    # Regression check: the original "Weekday DD:" (no slash) shape must
    # keep working after loosening the regex for the M/D case above.
    days = _parse_lunch_menu_days(_REAL_DESCRIPTION, year=2026, month=9)
    assert len(days) == 4


# --- _infer_lunch_menu_start_date -------------------------------------------

_EXTRACTED_AT = datetime(2026, 9, 10, tzinfo=ZoneInfo("America/New_York"))


def test_infers_month_from_item_title():
    item = {"title": "September Lunch Menu", "description": "..."}
    d = _infer_lunch_menu_start_date(item, _EXTRACTED_AT)
    assert (d.year, d.month, d.day) == (2026, 9, 1)


def test_infers_month_and_year_when_both_present():
    item = {"title": "October 2027 Lunch Menu", "description": "..."}
    d = _infer_lunch_menu_start_date(item, _EXTRACTED_AT)
    assert (d.year, d.month, d.day) == (2027, 10, 1)


def test_falls_back_to_extraction_time_when_no_month_mentioned():
    item = {"title": "Lunch Menu", "description": "Nothing dated here"}
    d = _infer_lunch_menu_start_date(item, _EXTRACTED_AT)
    assert (d.year, d.month, d.day) == (2026, 9, 1)


# --- _prepare_image / _sniff_media_type -------------------------------------
# Real failures seen on the first prod extraction run: Smore's CDN served a
# PNG with a Content-Type of image/jpeg, another image with a media type the
# vision API doesn't accept at all, and one flyer big enough to trip the
# request size limit - all three were logged and then silently dropped.
import io

from PIL import Image

from services.content_extractor import _MAX_IMAGE_EDGE, _prepare_image, _sniff_media_type


def _image_bytes(fmt: str, size=(40, 30)) -> bytes:
    buf = io.BytesIO()
    Image.new("RGB", size, (30, 120, 200)).save(buf, format=fmt)
    return buf.getvalue()


def test_media_type_comes_from_the_bytes_not_a_header():
    assert _sniff_media_type(_image_bytes("PNG")) == "image/png"
    assert _sniff_media_type(_image_bytes("JPEG")) == "image/jpeg"
    assert _sniff_media_type(_image_bytes("GIF")) == "image/gif"
    assert _sniff_media_type(b"RIFF\x00\x00\x00\x00WEBPVP8 ") == "image/webp"
    assert _sniff_media_type(b"<svg xmlns='http://www.w3.org/2000/svg'/>") is None


def test_small_supported_image_passes_through_untouched():
    png = _image_bytes("PNG")
    assert _prepare_image(png) == (png, "image/png")


def test_oversized_image_is_downscaled_to_the_api_edge_limit():
    wide = _image_bytes("PNG", size=(_MAX_IMAGE_EDGE * 3, 200))
    prepared = _prepare_image(wide)
    assert prepared is not None
    data, media_type = prepared
    assert media_type == "image/jpeg"
    with Image.open(io.BytesIO(data)) as img:
        assert max(img.size) <= _MAX_IMAGE_EDGE
        assert img.size[0] > img.size[1]  # aspect ratio kept


def test_unsupported_format_is_reencoded_rather_than_rejected():
    bmp = _image_bytes("BMP")
    assert _sniff_media_type(bmp) is None
    prepared = _prepare_image(bmp)
    assert prepared is not None
    assert prepared[1] == "image/jpeg"


def test_non_image_bytes_return_none_instead_of_raising():
    assert _prepare_image(b"<html>not an image</html>") is None
    assert _prepare_image(b"\x89PNG\r\n\x1a\ntruncated garbage") is None


# Regression cover for the Chesterbrook Academy Ice Cream Social (Sept
# 2026): the preschool PTA reused last year's flyer artwork, which prints
# "SEPTEMBER 24, 2025". Vision transcribed that faithfully, the extraction
# trusted the explicit year over a sibling block's bare "9/24", and the
# resulting 2025-dated item then superseded the correctly-dated 2026 rows -
# so the event disappeared from Coming up, Today and the calendar entirely.
_NY = ZoneInfo("America/New_York")
_REF = datetime(2026, 9, 15, 9, 0, tzinfo=_NY)


def test_last_years_flyer_date_is_rolled_forward_to_this_year():
    # The real case: "SEPTEMBER 24, 2025", 5:30pm, scanned Sept 2026.
    corrected = _correct_stale_year(datetime(2025, 9, 24, 17, 30, tzinfo=_NY), _REF)
    assert corrected == datetime(2026, 9, 24, 17, 30, tzinfo=_NY)


def test_an_upcoming_date_is_left_untouched():
    upcoming = datetime(2026, 9, 24, tzinfo=_NY)
    assert _correct_stale_year(upcoming, _REF) == upcoming


def test_a_just_passed_date_is_not_shoved_a_year_ahead():
    # Inside the 30-day grace: newsletters routinely still mention an event
    # a week or two after it happened, and that is not a stale year.
    just_passed = datetime(2026, 9, 1, tzinfo=_NY)
    assert _correct_stale_year(just_passed, _REF) == just_passed


def test_a_genuinely_historical_date_is_left_alone():
    # Further back than _MAX_YEAR_ROLL - a school-history mention, not a
    # mis-yeared current event, so guessing a year for it would be worse.
    historical = datetime(2019, 6, 1, tzinfo=_NY)
    assert _correct_stale_year(historical, _REF) == historical


def test_missing_date_passes_through():
    assert _correct_stale_year(None, _REF) is None


def test_leap_day_rolls_to_the_28th_rather_than_raising():
    assert _add_years(datetime(2024, 2, 29, tzinfo=_NY), 1) == datetime(2025, 2, 28, tzinfo=_NY)


def _item(title: str, start: datetime | None) -> SchoolContentItem:
    return SchoolContentItem(title=title, start_date=start)


def test_a_past_item_may_not_supersede_an_upcoming_one():
    # The exact swap that hid the Ice Cream Social.
    upcoming = _item("PTA Ice Cream Social", datetime(2026, 9, 24, tzinfo=_NY))
    stale = _item("PTA Ice Cream Social", datetime(2025, 9, 24, 17, 30, tzinfo=_NY))
    assert _may_supersede(upcoming, stale, _REF) is False


def test_a_corrected_upcoming_item_may_still_supersede():
    # The case supersede exists for: same event, corrected date/details.
    old = _item("Back to School Night", datetime(2026, 9, 22, tzinfo=_NY))
    new = _item("Back to School Night", datetime(2026, 9, 23, 18, 30, tzinfo=_NY))
    assert _may_supersede(old, new, _REF) is True


def test_items_without_dates_may_still_supersede():
    old = _item("Nut-Free Policy", None)
    new = _item("Nut-Free Policy", None)
    assert _may_supersede(old, new, _REF) is True


# Dedup is first-wins, and which block gets extracted first is arbitrary.
# Real case: East announced "Back to School Night" in four per-cohort
# "important dates" lists carrying no description at all, plus a dedicated
# flyer block with the full paragraph - and the flyer was extracted last, so
# a bare skip kept an empty row and threw the only useful copy away.


def test_an_empty_description_is_filled_from_the_duplicate():
    existing = SchoolContentItem(title="Back to School Night", description=None)
    filled = _backfill_from_duplicate(existing, {"description": "Begins promptly at 7:00 PM."}, None)
    assert filled is True
    assert existing.description == "Begins promptly at 7:00 PM."


def test_an_existing_description_is_never_overwritten():
    # "Longer" is not reliably "better", so a populated field is left alone.
    existing = SchoolContentItem(title="Picture Day", description="Grades 10, 11, 9 and Faculty/Staff.")
    changed = _backfill_from_duplicate(existing, {"description": "Sophomores, Juniors, and Freshmen."}, None)
    assert changed is False
    assert existing.description == "Grades 10, 11, 9 and Faculty/Staff."


def test_a_missing_link_is_filled_from_the_duplicate():
    existing = SchoolContentItem(title="Back to School Night", description="x", link_url=None)
    assert _backfill_from_duplicate(existing, {"description": "x"}, "https://example.org/bts") is True
    assert existing.link_url == "https://example.org/bts"


def test_a_whitespace_only_description_counts_as_empty():
    existing = SchoolContentItem(title="Picture Day", description="   ")
    assert _backfill_from_duplicate(existing, {"description": "CADY is the new photographer."}, None) is True
    assert existing.description == "CADY is the new photographer."


def test_nothing_to_backfill_reports_no_change():
    existing = SchoolContentItem(title="Picture Day", description="Already here.", link_url="https://e.org")
    assert _backfill_from_duplicate(existing, {"description": "Other wording."}, "https://other.org") is False
    assert existing.link_url == "https://e.org"
