from services.ptboard_parser import _extract_feed_items

_PAGE_URL = "https://haspta.ptboard.com/home"

# Confirmed real shape from Haviland Avenue Elementary's haspta.ptboard.com/home.
_REAL_SECTION = """
<div class="content-summary-section">
    <div class="header">
        <div class="row">
            <div class="small-8 columns left">Forms &amp; Payments</div>
        </div>
    </div>
    <div class="feed-items">
        <a class="feed-item" href="/formvw?store=8677&amp;form=2">
            <div class="feed-body">
                <div class="feed-row1">
                    <span class="type-tag form">Form &amp; Payment</span>
                    <span class="timestamp">Closes 12/18/2026 3:36pm</span>
                </div>
                <div class="feed-title">PTA Involvement Form</div>
                <div class="feed-desc">Do you have ideas of how you'd like to pitch in?</div>
            </div>
        </a>
    </div>
</div>
"""


def test_extracts_real_feed_item_shape():
    items = _extract_feed_items(_REAL_SECTION, _PAGE_URL)
    assert len(items) == 1
    item = items[0]
    assert item["link_url"] == "https://haspta.ptboard.com/formvw?store=8677&form=2"
    assert item["block_type"] == "text"
    assert "Forms & Payments" in item["text_content"]
    assert "Form & Payment" in item["text_content"]
    assert "PTA Involvement Form" in item["text_content"]
    assert "Closes 12/18/2026 3:36pm" in item["text_content"]
    assert "Do you have ideas" in item["text_content"]


def test_relative_href_resolved_against_page_url():
    items = _extract_feed_items(_REAL_SECTION, _PAGE_URL)
    assert items[0]["link_url"].startswith("https://haspta.ptboard.com/")


def test_content_hash_is_stable_and_href_specific():
    items = _extract_feed_items(_REAL_SECTION, _PAGE_URL)
    again = _extract_feed_items(_REAL_SECTION, _PAGE_URL)
    assert items[0]["content_hash"] == again[0]["content_hash"]

    other = _REAL_SECTION.replace("form=2", "form=3")
    other_items = _extract_feed_items(other, _PAGE_URL)
    assert other_items[0]["content_hash"] != items[0]["content_hash"]


def test_multiple_sections_and_items_all_captured():
    html = _REAL_SECTION + _REAL_SECTION.replace("form=2", "form=3").replace(
        "Forms &amp; Payments", "Announcements"
    )
    items = _extract_feed_items(html, _PAGE_URL)
    assert len(items) == 2
    assert items[0]["position"] == 0
    assert items[1]["position"] == 1


def test_item_with_no_href_is_skipped():
    html = """
    <div class="content-summary-section">
        <div class="header"><div class="left">Announcements</div></div>
        <div class="feed-items"><a class="feed-item"><div class="feed-title">No link</div></a></div>
    </div>
    """
    assert _extract_feed_items(html, _PAGE_URL) == []


def test_no_sections_returns_empty():
    assert _extract_feed_items("<div>Nothing here</div>", _PAGE_URL) == []
