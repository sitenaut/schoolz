from pathlib import Path

from services.staff_roster import _parse_tablepress_directory

FIXTURES = Path(__file__).parent / "fixtures"


def test_tablepress_directory_reads_name_title_and_obfuscated_email():
    items = _parse_tablepress_directory((FIXTURES / "haddonfield_staff_directory_high.html").read_text())
    assert len(items) > 60
    ad = next(i for i in items if i["title"] == "Athletic Director")
    assert ad["full_name"].endswith("Banos")
    assert ad["email"].endswith("@haddonfield.k12.nj.us")
    # letter headers ("B") are section dividers, never people
    assert not any(i["full_name"] in {"A", "B", "C"} for i in items)


def test_tablepress_directory_department_header_applies_to_untitled_people():
    items = _parse_tablepress_directory((FIXTURES / "haddonfield_staff_directory_central.html").read_text())
    assert any(i["department"] == "Kindergarten" and not i["title"] for i in items)
    assert any(i["title"] == "Principal" for i in items)


def test_smore_short_link_counts_as_an_issue_but_author_profile_does_not():
    from services.smore_parser import _SMORE_ISSUE_HREF_RE as r

    assert r.match("https://www.smore.com/136jk")
    assert r.match("https://secure.smore.com/n/e7tky")
    assert not r.match("https://www.smore.com/u/someauthor")
    assert not r.match("https://www.smore.com/")
