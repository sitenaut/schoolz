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


def test_eschoolview_footer_reads_plain_address_lines_and_directory_relative_logo():
    from services.school_info import _parse_eschoolview_footer

    html = (
        "<html><body><header><img src='sysimages/Logos/Countryside.png'></header>"
        "<div>Menu</div><div>PTO</div><div>115 Schoolhouse Lane</div>"
        "<div>Mount Laurel, NJ 08054</div><div>Phone: (856) 234-2750</div></body></html>"
    )
    info = _parse_eschoolview_footer(html, "https://www.mtlaurelschools.org/countrysideelementary_home.aspx")
    assert info == {
        "address": "115 Schoolhouse Lane, Mount Laurel, NJ 08054",
        "main_phone": "(856) 234-2750",
        "logo_url": "https://www.mtlaurelschools.org/sysimages/Logos/Countryside.png",
    }
    assert _parse_eschoolview_footer("<html><body>nothing</body></html>", "https://x.org/a.aspx") is None


def test_edlio_footer_gives_address_and_phone_and_other_platforms_fall_through():
    from services.school_info import _parse_edlio_footer

    html = (
        '<div class="footer-info-block"><a href="/apps/maps">162 Stokes Road, Medford, NJ 08055</a></div>'
        '<div class="footer-info-block">Phone: <a href="tel:+16096544056">(609) 654-4056 </a></div>'
    )
    r = _parse_edlio_footer(html, "https://x.test")
    assert (r["address"], r["main_phone"]) == ("162 Stokes Road, Medford, NJ 08055", "(609) 654-4056")
    assert _parse_edlio_footer("<footer>nothing</footer>", "https://x.test") is None
