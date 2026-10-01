from datetime import date
from pathlib import Path

from services.lunch_menu import _classify_abbreviated_pdf_link, _classify_numeric_pdf_link
from services.staff_roster import _decode_cf_email, _parse_table_page, _parse_wp_card_page

FIXTURES = Path(__file__).parent / "fixtures"


def test_yearless_abbreviated_menu_infers_the_nearest_year():
    # Magnolia's real filenames: the same name every year, no year at all.
    sept = _classify_abbreviated_pdf_link(".../SEPTLUNCHMENU.pdf", "elementary", today=date(2026, 10, 1))
    assert sept["meal_type"] == "lunch"
    assert sept["period_label"] == "September 2026"
    assert sept["_sort"] == (2026, 8)
    # Late December looking at a January menu is next year's, not eleven months ago.
    jan = _classify_abbreviated_pdf_link(".../JANLUNCHMENU.pdf", "elementary", today=date(2026, 12, 28))
    assert jan["period_label"] == "January 2027"


def test_abbreviated_menu_with_explicit_year_is_unchanged():
    result = _classify_abbreviated_pdf_link(".../MERSept26LunchMenu_1.pdf", "elementary", today=date(2030, 1, 1))
    assert result["period_label"] == "September 2026"


def test_numeric_month_menu_is_laurel_springs_shape():
    result = _classify_numeric_pdf_link(".../uploads/2026/09/2026-09-Lunch-Menu-LSS.pdf", "elementary")
    assert result["meal_type"] == "lunch"
    assert result["period_label"] == "September 2026"
    assert result["_sort"] == (2026, 8)
    assert _classify_numeric_pdf_link(".../2026-13-Lunch-Menu.pdf", "elementary") is None
    assert _classify_numeric_pdf_link(".../2026-2027-LSS-Calendar-2.pdf", "elementary") is None


def test_table_page_reads_both_staff_tables():
    items = _parse_table_page((FIXTURES / "magnolia_staff_page.html").read_text())
    by_name = {i["full_name"]: i for i in items}
    teacher = by_name["Mrs. Stacey Dobleman"]
    assert teacher["title"] == "PreK-1"
    assert teacher["email"] == "sdobleman@magnoliaschools.org"
    assert teacher["phone"] is None  # "118" is a room, not a phone number
    assert by_name["Mrs. Sandy Marlys"]["title"] == "Nurse"
    # Second table has "Position" in the first column, and a typed-in phone with no email.
    assert by_name["Mr. Paul Sorrentino"]["title"] == "Principal"
    business = by_name["Mr. Greg Gontowski"]
    assert business["phone"] == "856.962.8822"
    assert business["email"] is None
    assert by_name["Ms. Brittany Leviege"]["email"] is None
    assert len({i["constituent_id"] for i in items}) == len(items)


def test_table_page_ignores_unrelated_tables():
    assert _parse_table_page("<table><tr><td>Day</td><td>Menu</td></tr><tr><td>Mon</td><td>Pizza</td></tr></table>") == []


def test_cloudflare_email_decodes():
    # The first byte is the XOR key for the rest.
    assert _decode_cf_email("/cdn-cgi/l/email-protection#dcb7b4bdb5b2b9af9cb0bda9aeb9b0afacaeb5b2bbafbfb4b3b3b0f2b3aebb")
    assert _decode_cf_email("/cdn-cgi/l/email-protection#zz") is None
    assert _decode_cf_email("/cdn-cgi/l/email-protection") is None


def test_wordpress_cards_decode_email_and_keep_staff_without_one():
    items = _parse_wp_card_page((FIXTURES / "laurel_springs_faculty_page.html").read_text())
    assert len(items) == 8
    by_name = {i["full_name"]: i for i in items}
    principal = by_name["Mrs. Lacovara"]
    assert principal["title"] == "Principal"
    assert principal["email"] and principal["email"].endswith("laurelspringschool.org")
    # No email button on a custodian's or aide's card: still a person to list.
    assert by_name["Mr. Molina"]["email"] is None
    assert by_name["Mr. Molina"]["title"] == "Custodian"
    assert len({i["constituent_id"] for i in items}) == len(items)


def test_policy_folder_children_are_not_handbooks():
    from services.school_documents import _find_doc_anchors

    html = (
        '<a href="/policieshibhandbook/policieshibhandbook/residency">Residency</a>'
        '<a href="/policieshibhandbook/handbook">Policies, HIB &amp; Handbook</a>'
        '<a href="/parent-student-handbook">Handbook</a>'
    )
    urls = [a["url"] for a in _find_doc_anchors(html, "https://x.org")]
    assert "https://x.org/policieshibhandbook/policieshibhandbook/residency" not in urls
    assert "/parent-student-handbook" in urls or "https://x.org/parent-student-handbook" in urls
