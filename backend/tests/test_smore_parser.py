from bs4 import BeautifulSoup

from services.smore_parser import _classify, _find_author_profile_link, _pick_current_issue_link


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


def test_video_embed_block_uses_title_and_link_not_the_placeholder_image():
    # Confirmed real: a YouTube embed on Cherry Hill East's newsletter puts
    # a base64 SVG play-icon placeholder in the foreground <img src> (not a
    # fetchable URL - vision-extraction would crash trying to GET a data:
    # URI) while the real title/link live on the video button's own
    # data-* attributes.
    block = _block(
        '<div class="block-wrapper"><div data-block-type="embed.video">'
        '<button data-video-title="SEPAG Back To School 2026" '
        'data-video-original-url="https://www.youtube.com/embed/IcDfgluY82I">'
        '<img role="presentation" src="data:image/svg+xml;base64,AAAA">'
        "</button></div></div>"
    )
    result = _classify(block)
    assert result["block_type"] == "text"
    assert result["text_content"] == "Video: SEPAG Back To School 2026"
    assert result["link_url"] == "https://www.youtube.com/embed/IcDfgluY82I"
    assert result["image_url"] is None


def test_image_with_data_uri_src_falls_back_to_text_not_a_bad_image_url():
    block = _block('<div class="block-wrapper"><img src="data:image/png;base64,AAAA"><p>Caption text</p></div>')
    result = _classify(block)
    assert result["block_type"] == "text"
    assert result["image_url"] is None


def test_picks_latest_dated_issue_from_a_real_archive_page():
    # Confirmed real shape: Cherry Hill's James F. Cooper Elementary lists
    # every issue with its date as the link text, oldest first.
    html = """
    <a href="https://app.smore.com/n/dz5ck">August 26, 2026</a>
    <a href="https://app.smore.com/n/uqfmj">September 4, 2026</a>
    <a href="https://app.smore.com/n/0mhat">September 10, 2026</a>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/0mhat"


def test_picks_latest_even_when_archive_lists_newest_first():
    html = """
    <a href="https://app.smore.com/n/0mhat">September 10, 2026</a>
    <a href="https://app.smore.com/n/uqfmj">September 4, 2026</a>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/0mhat"


def test_falls_back_to_last_link_in_document_order_when_no_date_parses():
    html = """
    <a href="https://app.smore.com/n/dz5ck">Read now</a>
    <a href="https://app.smore.com/n/0mhat">Read now</a>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/0mhat"


def test_ignores_a_smore_author_profile_link_not_an_issue_link():
    # Confirmed real: a site nav can link smore.com/u/<username> (an author
    # profile listing every newsletter that author has ever published, not
    # any one issue) alongside the real per-issue links.
    html = """
    <a href="https://www.smore.com/u/someauthor">All Newsletters</a>
    <a href="https://app.smore.com/n/0mhat">September 10, 2026</a>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/0mhat"


def test_no_smore_links_returns_none():
    assert _pick_current_issue_link("<a href='/about'>About</a>") is None


def test_picks_link_with_explicit_current_issue_label():
    # Confirmed real: Audubon HS's "Counselor's Corner" link text.
    html = """
    <a href="https://app.smore.com/n/older">Past Issue</a>
    <a href="https://app.smore.com/n/current">CURRENT ISSUE OF THE COUNSELOR'S CORNER</a>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/current"


def test_finds_smore_link_embedded_as_an_iframe_src():
    # Confirmed real: Jennings Elementary's newsletter page has no <a
    # href> at all, just an <iframe src="...?embedded">.
    html = '<iframe src="https://app.smore.com/n/rxme5?embedded"></iframe>'
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/rxme5?embedded"


def test_picks_latest_from_leading_text_date_before_the_link():
    # Confirmed real shape: Audubon HS's /newsletters page - bare "Month
    # Year" text immediately before a link whose own text is just the URL.
    html = """
    <p>March 2026 <a href="https://app.smore.com/n/m8wrz">https://app.smore.com/n/m8wrz</a></p>
    <p>Winter 2026 <a href="https://app.smore.com/n/tz6a3">https://app.smore.com/n/tz6a3</a></p>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/m8wrz"


def test_picks_latest_from_last_edited_text_near_a_dateless_thumbnail_link():
    # Confirmed real shape: a Smore author profile's newsletter card has no
    # date in the link text itself - only nearby sibling text.
    html = """
    <div class="newsletter-container">
      <a href="https://app.smore.com/n/older-issue" aria-label="Edit">
        <img src="thumb1.jpg">
      </a>
      <div>Last edited September 1, 2025</div>
    </div>
    <div class="newsletter-container">
      <a href="https://app.smore.com/n/hny2pw-the-barton-scoop" aria-label="Edit">
        <img src="thumb2.jpg">
      </a>
      <div>Last edited October 3, 2025</div>
    </div>
    """
    assert _pick_current_issue_link(html) == "https://app.smore.com/n/hny2pw-the-barton-scoop"


def test_finds_author_profile_link_ignoring_issue_links():
    html = """
    <a href="https://app.smore.com/n/not-an-author-page">Some Issue</a>
    <a href="https://secure.smore.com/u/idalis.kizee">Principal's Updates</a>
    """
    assert _find_author_profile_link(html) == "https://secure.smore.com/u/idalis.kizee"


def test_find_author_profile_link_returns_none_when_absent():
    assert _find_author_profile_link('<a href="https://app.smore.com/n/x">X</a>') is None
