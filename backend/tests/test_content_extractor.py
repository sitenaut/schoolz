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
