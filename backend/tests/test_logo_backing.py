import io

from PIL import Image, ImageDraw

from services.logo_backing import classify_logo


def _png(ink, background=(0, 0, 0, 0), second_ink=None) -> bytes:
    """A 100x100 logo: an `ink` block on `background`, optionally with a
    `second_ink` block beside it."""
    image = Image.new("RGBA", (100, 100), background)
    draw = ImageDraw.Draw(image)
    draw.rectangle((20, 20, 49, 79), fill=ink)
    if second_ink:
        draw.rectangle((50, 20, 79, 79), fill=second_ink)
    out = io.BytesIO()
    image.save(out, format="PNG")
    return out.getvalue()


def test_white_ink_on_transparent_needs_a_dark_backing():
    assert classify_logo(_png((255, 255, 255, 255))) == "dark"


def test_dark_ink_on_transparent_needs_a_light_backing():
    assert classify_logo(_png((10, 10, 30, 255))) == "light"


def test_mid_tone_ink_is_visible_on_both_themes():
    assert classify_logo(_png((200, 40, 40, 255))) == "none"


def test_opaque_image_carries_its_own_box():
    # White ink on an opaque white ground is the district's problem, not a
    # backing's - the image is a visible box on either theme.
    assert classify_logo(_png((10, 10, 30, 255), background=(255, 255, 255, 255))) == "none"


def test_half_white_half_colour_gets_the_dark_backing():
    # e.g. a mascot with a white wordmark: half the artwork vanishes on light.
    assert classify_logo(_png((255, 255, 255, 255), second_ink=(200, 40, 40, 255))) == "dark"


def test_ink_of_both_kinds_backs_against_the_worse_theme():
    image = Image.new("RGBA", (100, 100), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rectangle((10, 10, 89, 49), fill=(255, 255, 255, 255))  # 40 rows of white
    draw.rectangle((10, 50, 89, 69), fill=(10, 10, 30, 255))  # 20 rows of dark
    out = io.BytesIO()
    image.save(out, format="PNG")
    assert classify_logo(out.getvalue()) == "dark"


def test_faint_antialiasing_does_not_count_as_ink():
    image = Image.new("RGBA", (100, 100), (255, 255, 255, 5))
    ImageDraw.Draw(image).rectangle((20, 20, 79, 79), fill=(200, 40, 40, 255))
    out = io.BytesIO()
    image.save(out, format="PNG")
    assert classify_logo(out.getvalue()) == "none"


def test_unreadable_image_is_left_alone():
    assert classify_logo(b"<svg xmlns='http://www.w3.org/2000/svg'/>") == "none"
    assert classify_logo(b"") == "none"
