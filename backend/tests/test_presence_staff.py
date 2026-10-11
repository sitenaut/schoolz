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


def test_presence_system_groups_are_not_staff(monkeypatch):
    """Gateway's /district/staff_directory lists every login account under
    "Registered Users" (and Parents/Students roles) beside the real
    department groups. Only the department groups are staff."""
    import asyncio

    import httpx

    from services import staff_roster

    page = '<div class="staffDirectoryComponent" data-portlet-instance-id="42"></div>'
    groups = [
        {"groupID": 1, "name": "Registered Users"},
        {"groupID": 2, "name": "Students"},
        {"groupID": 3, "name": "Science"},
    ]
    people = {
        1: [{"userID": 9, "firstName": "Login", "lastName": "Only", "jobTitle": "", "email": "x@example.org"}],
        2: [{"userID": 8, "firstName": "Some", "lastName": "Student", "jobTitle": "", "email": ""}],
        3: [{"userID": 7, "firstName": "Pat", "lastName": "Teacher", "jobTitle": "Teacher", "email": "pt@example.org"}],
    }

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, **k):
            code = 200 if url.endswith("/district/staff_directory") else 404
            return httpx.Response(code, text=page, request=httpx.Request("GET", url))

        async def post(self, url, json=None, headers=None):
            if url.endswith("/Settings"):
                body = {"d": {"groups": groups}}
            else:
                body = {"d": {"results": people[json["groupIds"][0]]}}
            return httpx.Response(200, json=body, request=httpx.Request("POST", url))

    monkeypatch.setattr(staff_roster.httpx, "AsyncClient", FakeClient)
    items = asyncio.run(staff_roster._fetch_presence_roster("https://www.gateway.test"))
    assert [i["full_name"] for i in items] == ["Pat Teacher"]
    assert items[0]["department"] == "Science" and items[0]["email"] == "pt@example.org"
