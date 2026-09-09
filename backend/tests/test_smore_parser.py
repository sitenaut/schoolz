from bs4 import BeautifulSoup

from services.smore_parser import _classify


def _block(html: str):
    return BeautifulSoup(html, "lxml").select_one(".block-wrapper")


def test_image_only_block_flagged_for_vision_extraction():
    block = _block('<div class="block-wrapper"><img src="https://cdn.smore.com/x.png" alt=""></div>')
    result = _classify(block)
    assert result["block_type"] == "image"
    assert result["image_url"] == "https://cdn.smore.com/x.png"
    assert result["text_content"] is None


def test_text_block():
    block = _block('<div class="block-wrapper"><p>Early dismissal is at 1pm Friday.</p></div>')
    result = _classify(block)
    assert result["block_type"] == "text"
    assert "Early dismissal" in result["text_content"]


def test_empty_decorative_block_is_skipped():
    block = _block('<div class="block-wrapper"><div class="spacer"></div></div>')
    assert _classify(block) is None


def test_same_content_hashes_identically_for_dedup():
    a = _classify(_block('<div class="block-wrapper"><p>Same text</p></div>'))
    b = _classify(_block('<div class="block-wrapper"><p>Same text</p></div>'))
    assert a["content_hash"] == b["content_hash"]


def test_different_text_hashes_differently():
    a = _classify(_block('<div class="block-wrapper"><p>Version one</p></div>'))
    b = _classify(_block('<div class="block-wrapper"><p>Version two</p></div>'))
    assert a["content_hash"] != b["content_hash"]


def test_link_in_real_anchor_is_captured_even_on_image_block():
    block = _block(
        '<div class="block-wrapper"><img src="https://cdn.smore.com/x.png" alt="">'
        '<a href="https://example.com/handbook">Handbook</a></div>'
    )
    result = _classify(block)
    assert result["block_type"] == "image"
    assert result["link_url"] == "https://example.com/handbook"


def test_zoom_control_chrome_is_stripped_from_image_text_content():
    # Confirmed real bug: Smore's hover-only "zoom" control (a Material
    # Icons ligature "zoom_out_map" plus a screen-reader-only "Show in
    # original size" caption) was being captured as the block's
    # text_content on every image block - content_extractor.py favors
    # text_content over vision_extracted_text when both are present, so
    # this silently discarded ALL vision-extracted flyer content
    # project-wide (Back to School Night flyers, lunch menus, "Mark Your
    # Calendar" lists all went missing). text_content must be None here so
    # the vision-extracted text is what reaches extraction.
    block = _block(
        '<div class="block-wrapper"><img src="https://cdn.smore.com/x.png" alt="">'
        '<a class="fancy-pic material-icons" aria-label="Show image in original size">'
        'zoom_out_map<span class="sr-only">Show in original size</span></a></div>'
    )
    result = _classify(block)
    assert result["block_type"] == "image"
    assert result["text_content"] is None


def test_real_caption_text_on_image_block_is_still_captured():
    # The zoom-control removal must not eat a genuine caption sitting
    # alongside an image.
    block = _block(
        '<div class="block-wrapper"><img src="https://cdn.smore.com/x.png" alt="">'
        "<p>Photo from the Fall Festival</p>"
        '<a class="fancy-pic material-icons" aria-label="Show image in original size">'
        "zoom_out_map</a></div>"
    )
    result = _classify(block)
    assert result["text_content"] == "Photo from the Fall Festival"


def test_bare_url_in_text_is_captured_when_no_anchor_tag():
    # Confirmed real case: a handbook link rendered as plain auto-detected
    # text inside an image block, not a real <a href>.
    block = _block(
        '<div class="block-wrapper"><img src="https://cdn.smore.com/x.png" alt="">'
        "<p>Click here: https://docs.google.com/document/d/abc123/edit</p></div>"
    )
    result = _classify(block)
    assert result["link_url"] == "https://docs.google.com/document/d/abc123/edit"
