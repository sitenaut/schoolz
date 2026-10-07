import base64
from pathlib import Path

from services import smart_sites

FIX = Path(__file__).parent / "fixtures"
HOME = (FIX / "smart_sites_home.html").read_text()
DIRECTORY = (FIX / "smart_sites_directory.html").read_text()


def test_recognises_smart_sites_only():
    assert smart_sites.is_smart_sites(HOME)
    assert not smart_sites.is_smart_sites('<html><div class="fsLocationAddress">1 Main St</div></html>')


def test_footer_address_and_phone():
    assert smart_sites.parse_footer(HOME) == {"address": "190 Tomlinson Mill Road, Marlton, NJ 08053", "main_phone": "856-988-9811"}


def test_directory_link_found_from_nav():
    links = smart_sites.find_directory_links(HOME, "https://x.evesham.k12.nj.us")
    assert links[0] == "https://x.evesham.k12.nj.us/435465_2"
    assert links[-1] == "https://x.evesham.k12.nj.us/staff-directory"


def test_widget_item_id_from_page_script():
    assert smart_sites.directory_item_ids("<script>getOnDemandDirectoryContent('2209841', false, '', '');</script>") == ["2209841"]
    assert smart_sites.directory_item_ids("<p>hand-typed list</p>") == []


def test_parse_directory_decodes_emails_and_drops_blank_slots():
    staff = smart_sites.parse_directory(DIRECTORY)
    assert len(staff) == 9
    delfino = next(s for s in staff if s["full_name"] == "Suzanne Delfino")
    assert delfino["email"] == "delfinos@evesham.k12.nj.us"
    assert delfino["title"] == "1st Grade Teacher"
    assert delfino["constituent_id"] == "ss:delfinos@evesham.k12.nj.us"
    assert len({s["constituent_id"] for s in staff}) == 9


def test_bad_email_payload_is_none_not_a_crash():
    card = (
        '<div class="staff-item"><div class="stack-directory-name">A B</div>'
        f'<button data-staff-email="{base64.b64encode(b"not-an-email").decode()}"></button></div>'
    )
    (only,) = smart_sites.parse_directory(card)
    assert only["email"] is None and only["constituent_id"] == "ss:a-b"


def test_handtyped_directories_are_parsed_role_first_and_name_first():
    from services import handtyped_directory as hd

    beeler = (
        "<div id='page-content-wrapper'><p>Office</p><p>Principal - Ryan Mahlman</p><p>Nurse &ndash; Jennifer Morrell</p>"
        "<p>Kindergarten</p><p>Shayna Fehrle</p><p>Music: Meredith Lowden</p><p>Instrumental Music/Band: Vince Pagliaro &amp; Tamara Kimler</p>"
        "<p>School Nurse</p></div>"
    )
    got = {p["full_name"]: p["title"] for p in hd.parse(beeler)}
    assert got["Ryan Mahlman"] == "Principal" and got["Jennifer Morrell"] == "Nurse"
    assert got["Shayna Fehrle"] == "Kindergarten Teacher"
    assert got["Vince Pagliaro"] == got["Tamara Kimler"] == "Instrumental Music/Band"
    assert "School Nurse" not in got

    rice = (
        "<div id='page-content-wrapper'><table><tr><td>Office</td><td></td><td>Speech</td></tr>"
        "<tr><td>Beverly Green - Principal</td><td></td><td>Lisa Bisti - Speech</td></tr>"
        "<tr><td>Kelsey Marshall- Nurse</td><td></td><td>Tara Talbot</td></tr>"
        "<tr><td>Chipana &amp; Robayo - World Language</td><td></td><td></td></tr></table></div>"
    )
    got = {p["full_name"]: p["title"] for p in hd.parse(rice)}
    assert got["Beverly Green"] == "Principal" and got["Kelsey Marshall"] == "Nurse"
    assert got["Tara Talbot"] == "Speech"
    assert len(got) == 4


def _fx(name):
    import pathlib

    return (pathlib.Path(__file__).parent / "fixtures" / f"{name}.html").read_text(encoding="utf-8")


def test_role_pages_name_a_person_only_where_the_page_places_one():
    from services import role_pages

    counselor = role_pages.parse_page(_fx("role_page_counselor"), "School Counselor")
    assert counselor == {"full_name": "Stephanie Rice", "title": "School Counselor", "email": "rices@evesham.k12.nj.us"}
    ap = role_pages.parse_page(_fx("role_page_ap"), "Assistant Principal")
    assert ap["full_name"] == "Bill Leonardo" and ap["email"] is None
    principal = role_pages.parse_page(_fx("role_page_principal_signed"), "Principal")
    assert (principal["full_name"], principal["email"]) == ("Amanda Fry", "frya@evesham.k12.nj.us")
    bio = role_pages.parse_page(_fx("role_page_counselor_bio"), "School Counselor")
    assert (bio["full_name"], bio["email"]) == ("Rosemarie Thackston", "thackstonr@evesham.k12.nj.us")
    assert role_pages.parse_page(_fx("role_page_nurse"), "School Nurse") is None


def test_role_links_come_from_the_nav_and_principals_message_is_the_principal():
    from services import role_pages

    home = '<a href="/nurse">Nurse</a><a href="/principalsmessage">Principal\'s Message</a><a href="/lunch">Lunch</a><a href="/nurse">Nurse</a>'
    assert role_pages.find_role_links(home, "https://x.example") == [
        ("Nurse", "https://x.example/nurse"),
        ("Principal", "https://x.example/principalsmessage"),
    ]


def test_footer_phone_drops_the_country_code():
    html = '<footer><a href="tel:+18568297770" aria-label="Phone +1 856-829-7770">+1 856-829-7770</a></footer>'
    assert smart_sites.parse_footer(html)["main_phone"] == "856-829-7770"
