"""parse_pdf_directory reads a staff directory published as a PDF table.

pdfplumber is stubbed with the rows it returns for the real sheet's shape, so
no real staff names live in the repo."""

import pytest

from services import staff_roster

HEADER = ["DEPARTMENT", "TITLE", "Name", "EMAIL", "EXTENSION"]
ROWS = [
    HEADER,
    ["Administration", "Principal", "Pat Example", "pexample@school.test", "65605"],
    ["Athletics", "Trainer", "Sam Sample", "ssample@school.test>", ""],  # stray ">" from hand typing
    ["Teacher", "Teacher", "Vacant", "", "34602"],  # an empty slot
    ["Conference Room", "Conference Room", "Main Office Conference Room", "", "34440"],
    ["Enrollment", "Enrollment", "Veronica/Joey", "", "856-536-3999"],  # a shared desk, not a person
    ["Office", "Clerk", "Alex Doe", "", "856-555-0100"],  # no email, full phone
    ["Office", "Clerk", "Alex Doe", "", "856-555-0100"],  # listed twice
]


class _Page:
    def __init__(self, tables):
        self._tables = tables

    def extract_tables(self):
        return self._tables


class _Pdf:
    def __init__(self, pages):
        self.pages = pages

    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


@pytest.fixture
def stub_pdf(monkeypatch):
    def install(*tables_per_page):
        monkeypatch.setattr(
            staff_roster.pdfplumber, "open", lambda _b: _Pdf([_Page(t) for t in tables_per_page])
        )

    return install


def test_keeps_people_and_cleans_email(stub_pdf):
    stub_pdf([ROWS])
    by_name = {e["full_name"]: e for e in staff_roster.parse_pdf_directory(b"")}
    assert set(by_name) == {"Pat Example", "Sam Sample", "Alex Doe"}
    assert by_name["Sam Sample"]["email"] == "ssample@school.test"
    assert by_name["Pat Example"]["department"] == "Administration"
    assert by_name["Pat Example"]["title"] == "Principal"
    # An extension alone isn't a dialable number; a full phone is kept.
    assert by_name["Pat Example"]["phone"] is None
    assert by_name["Alex Doe"]["phone"] == "856-555-0100"


def test_identity_is_email_else_name_and_title(stub_pdf):
    stub_pdf([ROWS])
    ids = {e["full_name"]: e["constituent_id"] for e in staff_roster.parse_pdf_directory(b"")}
    assert ids["Pat Example"] == "pdf:pexample@school.test"
    assert ids["Alex Doe"] == "pdf:alex-doe|clerk"


def test_columns_found_by_header_not_position(stub_pdf):
    stub_pdf([[["Email", "Name", "Title"], ["a@b.test", "Kim Reorder", "Nurse"]]])
    (entry,) = staff_roster.parse_pdf_directory(b"")
    assert (entry["full_name"], entry["email"], entry["title"], entry["department"]) == (
        "Kim Reorder", "a@b.test", "Nurse", None,
    )


def test_header_repeated_on_each_page_and_no_header_table_ignored(stub_pdf):
    stub_pdf([ROWS[:2]], [[["junk", "cells"]], ROWS[:1] + [ROWS[2 - 1 + 1]]])
    names = [e["full_name"] for e in staff_roster.parse_pdf_directory(b"")]
    assert "Pat Example" in names and "junk" not in names


SLIDES = """Example Family School
Staff Contact
pg 11
Teacher Email Addresses

Pre-k
Ms. One
one@school.test
 Ms. Two
two@school.test
1st Grade
Ms. Typo
typo@schol.test
Ms. Curly
o’curly@school.test
Middle School
Mr. Math (Math)
math@school.test
Special Areas
(PE/Health)
Mr. King (PE/Health)
king@school.test
Ms. Repeat (4th-5th)
two@school.test
"""


def test_slides_directory_names_titles_and_emails():
    by_name = {e["full_name"]: e for e in staff_roster.parse_slides_directory(SLIDES)}
    assert by_name["Ms. One"]["title"] == "Pre-k" and by_name["Ms. One"]["email"] == "one@school.test"
    assert by_name["Mr. Math"]["title"] == "Middle School (Math)"
    assert by_name["Mr. King"]["title"] == "Special Areas (PE/Health)"  # "(PE/Health)" alone is not a heading
    assert "Staff Contact" not in by_name and "Example Family School" not in by_name


def test_slides_directory_drops_bad_addresses_keeps_people():
    by_name = {e["full_name"]: e for e in staff_roster.parse_slides_directory(SLIDES)}
    assert by_name["Ms. Typo"]["email"] is None  # domain differs from the list's own
    assert by_name["Ms. Curly"]["email"] is None  # curly apostrophe: not a valid address


def test_slides_directory_person_listed_twice_collapses_by_email():
    names = [e["full_name"] for e in staff_roster.parse_slides_directory(SLIDES)]
    assert "Ms. Two" not in names and names.count("Ms. Repeat") == 1


def test_header_printed_once_applies_to_later_pages_and_any_name_heading(stub_pdf):
    stub_pdf(
        [[["School Leadership", "Position", "Email"], ["Pat Lead", "Principal", "plead@school.test"],
          ["Staff Members", "Position", "Email"], ["Roe, Jordan", "Teacher", "jroe@school.test"]]],
        [[["Poe, Casey", "Nurse", "cpoe@school.test"]]],  # no header on this page
    )
    by_name = {e["full_name"]: e for e in staff_roster.parse_pdf_directory(b"")}
    assert set(by_name) == {"Pat Lead", "Jordan Roe", "Casey Poe"}  # "Last, First" -> "First Last"
    assert by_name["Casey Poe"]["title"] == "Nurse" and by_name["Casey Poe"]["email"] == "cpoe@school.test"


def test_suffix_is_not_mistaken_for_last_first():
    assert staff_roster._first_last("Smith, Jr.") == "Smith, Jr."
    assert staff_roster._first_last("Lee, Dana") == "Dana Lee"


def test_role_page_inline_person_needs_surname_in_address():
    from services import role_pages

    html = (
        "<main><h1>Nurse's Corner</h1><p>School Nurse Jane Doe 856-555-0100, extension 4 · jdoe@school.test</p>"
        '<a href="mailto:jdoe@school.test">Email</a><a href="mailto:hib@school.test">HIB</a></main>'
    )
    assert role_pages.parse_inline_page(html, "Nurse's Corner") == {
        "full_name": "Jane Doe", "title": "School Nurse", "email": "jdoe@school.test",
    }
    no_match = html.replace('<a href="mailto:jdoe@school.test">Email</a>', "").replace(" · jdoe@school.test", "")
    assert role_pages.parse_inline_page(no_match, "Nurse's Corner")["email"] is None


def test_xlsx_sections_each_with_own_header(tmp_path):
    import zipfile

    def cell(ref, text):
        return f'<c r="{ref}" t="inlineStr"><is><t>{text}</t></is></c>'

    rows = [
        [("A", "Offices")],
        [("A", "Subject"), ("B", "Name"), ("E", "Email")],
        [("A", "Nurse"), ("B", "Pat Nurse")],
        [("A", "Grade"), ("B", "Teacher"), ("E", "Email")],
        [("A", "Pre-K"), ("B", "Rae Teach"), ("E", "rteach@school.test")],
    ]
    xml = "<worksheet xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main'><sheetData>" + "".join(
        f"<row r='{i}'>" + "".join(cell(f"{c}{i}", t) for c, t in r) + "</row>" for i, r in enumerate(rows, 1)
    ) + "</sheetData></worksheet>"
    path = tmp_path / "s.xlsx"
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("xl/worksheets/sheet1.xml", xml)
        z.writestr("xl/worksheets/sheet2.xml", xml.replace("Rae Teach", "Other Sheet").replace("rteach@", "other@"))
    by_name = {e["full_name"]: e for e in staff_roster.parse_xlsx_directory(path.read_bytes())}
    assert by_name["Pat Nurse"]["title"] == "Nurse" and by_name["Pat Nurse"]["email"] is None
    assert by_name["Rae Teach"]["title"] == "Pre-K" and by_name["Rae Teach"]["email"] == "rteach@school.test"
    assert by_name["Other Sheet"]["email"] == "other@school.test"


def test_role_page_inline_title_after_name():
    from services import role_pages

    html = "<main><p>Jane Doe</p><p>School Nurse</p><p>Health Office Phone 856-555-0100</p><a href='mailto:jdoe@school.test'>x</a></main>"
    assert role_pages.parse_inline_page(html, "Nurse's Corner") == {
        "full_name": "Jane Doe", "title": "School Nurse", "email": "jdoe@school.test",
    }


def test_published_sheet_directory_joins_first_and_last_name():
    text = (
        "First Name,Last Name,E-Mail,Position,Ext.\r\n"
        ",,,,\r\n"
        "Pat,Nurse,pnurse@school.test,School Nurse,3024\r\n"
        "Rae,Teach,,Art Teacher,\r\n"
    )
    by_name = {e["full_name"]: e for e in staff_roster.parse_csv_directory(text)}
    assert set(by_name) == {"Pat Nurse", "Rae Teach"}
    assert by_name["Pat Nurse"] == {
        "constituent_id": "sheet:pnurse@school.test", "full_name": "Pat Nurse", "title": "School Nurse",
        "department": None, "email": "pnurse@school.test", "phone": None,
    }
    assert by_name["Rae Teach"]["email"] is None and by_name["Rae Teach"]["title"] == "Art Teacher"


def test_published_sheet_csv_url_keeps_the_tab():
    url = "https://docs.google.com/spreadsheets/d/e/2PACX-ab_c/pubhtml?gid=7&single=true&widget=true&headers=false"
    assert staff_roster.published_sheet_csv_url(url) == "https://docs.google.com/spreadsheets/d/e/2PACX-ab_c/pub?gid=7&single=true&output=csv"
    assert staff_roster.published_sheet_csv_url("https://docs.google.com/presentation/d/abc/edit") is None


def test_nurse_page_names_her_by_her_credentials():
    from services import role_pages

    def page(body):
        return f'<div id="page-content-wrapper"><h1>School Nurse Home</h1>{body}</div>'

    out = role_pages.parse_inline_page(page("<p>Welcome!</p><p>Mrs. Pat Doe, RN, BSN, CSN</p><p>(856) 555-0100 ext. 5803</p>"), "School Nurse Home")
    assert out == {"full_name": "Pat Doe", "title": "School Nurse", "email": None}
    out = role_pages.parse_inline_page(
        page('<p>Rae Roe BSN, RN, NJ-CSN</p><p>Email:</p><a href="mailto:roer@school.test">roer@school.test</a><a href="mailto:hib@school.test">x</a>'),
        "School Nurse",
    )
    assert out == {"full_name": "Rae Roe", "title": "School Nurse", "email": "roer@school.test"}
    out = role_pages.parse_inline_page(
        page("<p>Jane Black, BSN, CSN, RN</p><p>Contact Nurse Black</p><p>Example Middle School Nurse</p><p>555-8012 ext. 4864</p>"), "School Nurse"
    )
    assert out["full_name"] == "Jane Black"
    assert role_pages.parse_inline_page(page("<p>Contact Pat Doe, BSN, RN</p><p>829-7600 ext. 2870</p>"), "x")["full_name"] == "Pat Doe"
    assert role_pages.parse_inline_page(page("<p>Asthma Action Plan Packet</p><p>Routine Physical Policy</p>"), "School Nurse") is None
