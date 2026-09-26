from services.contact_page import find_contact_page, page_text, verified


def test_table_rows_stay_aligned():
    """Voorhees Middle's page is a table: titles in one row, names in the
    next. Read as plain text, a column layout loses which name is whose."""
    html = """<div id="fsPageContent"><table>
      <tr><td>Principal</td><td>Secretary</td></tr>
      <tr><td>Alecia Inge</td><td>Allison Ruff</td></tr>
      <tr><td>Email: inge@voorhees.k12.nj.us</td><td>Email: Ruff@voorhees.k12.nj.us</td></tr>
    </table></div>"""
    assert "Principal | Secretary\nAlecia Inge | Allison Ruff" in page_text(html)


def test_only_people_whose_email_and_name_are_on_the_page_survive():
    text = "Principal: Robert Cranmer\nCranmer@voorhees.k12.nj.us\nNurse: Vickie Crews\nCrews@voorhees.k12.nj.us"
    people = [
        {"name": "Robert Cranmer", "title": "Principal:", "email": "Cranmer@voorhees.k12.nj.us"},
        {"name": "Vickie Crews", "title": "Nurse", "email": "crews@voorhees.k12.nj.us", "phone": "856-428-2990 Ext. 4137"},
        {"name": "Invented Person", "title": "Counselor", "email": "invented@voorhees.k12.nj.us"},
        {"name": "Robert Cranmer", "title": "Principal", "email": "cranmer@voorhees.k12.nj.us"},  # duplicate
    ]
    out = verified(people, text)
    assert [(p["full_name"], p["title"], p["email"]) for p in out] == [
        ("Robert Cranmer", "Principal", "cranmer@voorhees.k12.nj.us"),
        ("Vickie Crews", "Nurse", "crews@voorhees.k12.nj.us"),
    ]
    assert out[0]["constituent_id"] == "contact-page:cranmer@voorhees.k12.nj.us"


def test_contact_page_link_must_stay_on_the_school_site():
    html = '<a href="https://www.voorhees.k12.nj.us/contact">Contact Us</a><a href="/osage-school/contact-us">Contact Us</a>'
    assert find_contact_page(html, "https://osage.voorhees.k12.nj.us/") == "https://osage.voorhees.k12.nj.us/osage-school/contact-us"
