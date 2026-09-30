from services.school_info import _parse_location

_ADDRESS = '<div class="fsLocationAddress">130 S. Centre Street</div><span class="fsLocationCity">Merchantville</span><span class="fsLocationState">NJ</span><span class="fsLocationZip">08109</span>'


def test_phone_from_tel_link():
    html = f'{_ADDRESS}<div class="fsLocationPhone"><a href="tel:8564280830">(856) 428-0830</a></div>'
    assert _parse_location(html, "https://x.org")["main_phone"] == "(856) 428-0830"


def test_phone_from_plain_text_footer():
    # Merchantville prints the number with a "P:" label and no tel: link.
    html = f'{_ADDRESS}<div class="fsLocationPhone">P: (856) 663-1091</div><div class="fsLocationFax">F: (856) 486-9755</div>'
    result = _parse_location(html, "https://x.org")
    assert result["main_phone"] == "(856) 663-1091"
    assert result["address"] == "130 S. Centre Street, Merchantville, NJ 08109"


def test_no_phone_widget_stays_none():
    assert _parse_location(_ADDRESS, "https://x.org")["main_phone"] is None
