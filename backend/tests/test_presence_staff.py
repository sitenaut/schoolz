import json
from pathlib import Path

from services.staff_roster import _parse_presence_search, _parse_presence_table_page

FIX = Path(__file__).parent / "fixtures"


def test_sterling_table_has_departments_titles_and_decoded_emails():
    items = _parse_presence_table_page((FIX / "sterling_staff_directory.html").read_text(encoding="utf8"))
    by_name = {i["full_name"]: i for i in items}
    principal = by_name["Jarod Claybourn"]
    assert principal["title"] == "Principal"
    assert principal["department"] == "Administration"
    assert "@" in principal["email"]
    assert by_name["Walter Young"]["department"] == "Art / Music"
    assert by_name["Walter Young"]["title"] == "Teacher"
    assert by_name["Jeanette Dean"]["title"] == "Admin. Asst. - Superintendent"
    assert all(i["full_name"].split()[0] not in ("Mr.", "Mrs.", "Ms.", "Dr.") for i in items)
    assert len({i["constituent_id"] for i in items}) == len(items)


def test_sterling_table_skips_spacer_and_header_rows():
    items = _parse_presence_table_page((FIX / "sterling_staff_directory.html").read_text(encoding="utf8"))
    assert all(i["full_name"].strip() and i["department"] for i in items)
    assert "Superintendent" not in {i["full_name"] for i in items}


def test_search_results_private_email_is_none_and_real_email_kept():
    data = json.loads((FIX / "somerdale_staff_search.json").read_text())["d"]["results"]
    items = _parse_presence_search(data, "Administrative Staff")
    private = [i for i in items if i["full_name"] != "Pat Example"]
    assert private and all(i["email"] is None for i in private)
    pat = next(i for i in items if i["full_name"] == "Pat Example")
    assert pat["email"] == "jdoe@example.org"
    assert pat["title"] is None
    assert pat["phone"] == "856-555-0100"
    assert pat["department"] == "Administrative Staff"


def test_presence_footer_both_template_variants():
    from services.school_info import _parse_presence_footer

    sterling = (
        '<div id="footer"><div class="schoolName"><img alt="Logo for Sterling High School" src="/UserFiles/logo.png"/>'
        'Sterling High School<div class="address">501 S. Warwick Road,\n   Somerdale,\n   New Jersey \n   08083</div>'
        '<div class="phone">Phone\r\n                  856-784-1333 | Fax 856-784-7661</div></div></div>'
    )
    out = _parse_presence_footer(sterling, "https://www.sterling.k12.nj.us")
    assert out["address"] == "501 S. Warwick Road, Somerdale, NJ 08083"
    assert out["main_phone"] == "856-784-1333"
    assert out["logo_url"].endswith("/UserFiles/logo.png")

    somerdale = (
        '<div id="footer-left"><h3>Somerdale Park School</h3><div id="footer-address">301 Grace St, Somerdale, NJ  08083'
        '<div>Phone <span class="footer-phone"></span>856-783-6261<span> | Fax <span>856-783-2607</span></span></div></div></div>'
    )
    out = _parse_presence_footer(somerdale, "https://www.somerdale-park.org")
    assert out["address"] == "301 Grace St, Somerdale, NJ 08083"
    assert out["main_phone"] == "856-783-6261"

    assert _parse_presence_footer("<footer>nothing</footer>", "https://x.org") is None

    delran = (
        '<ul class="address"><li><span class="fa fa-map"></span>50 Hartford Rd., Delran, NJ 08075</li>'
        '<li><span class="fa fa-phone"></span>856.461.6100</li>'
        '<li><span class="fax-n"><span class="fa fa-fax"></span><span class="footer-fax">856.764.6177</span></span></li></ul>'
    )
    out = _parse_presence_footer(delran, "https://dhs.example.org")
    assert out["address"] == "50 Hartford Rd., Delran, NJ 08075" and out["main_phone"] == "856.461.6100"
