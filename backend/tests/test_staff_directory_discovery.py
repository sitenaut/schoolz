from services import staff_roster


def test_directory_link_found_from_nav_same_site_only():
    home = (
        '<a href="/our-school/high-school-staff-directory">Staff Directory</a>'
        '<a href="/our-school/staff-websites">Staff Websites</a>'
        '<a href="https://www.district.test/district/contact-us/staff-directory">District Staff Directory</a>'
        '<a href="/parents/hsa-staff-member-of-the-month">Staff Member of the Month</a>'
        '<a href="/directory">Directory</a>'
    )
    assert staff_roster.find_directory_links(home, "https://lhs.district.test") == ["https://lhs.district.test/our-school/high-school-staff-directory"]


def test_link_named_in_text_outranks_one_named_only_in_its_path():
    home = '<a href="/x/staff-directory">People</a><a href="/about/who-we-are">Staff Directory</a>'
    assert staff_roster.find_directory_links(home, "https://s.test")[0] == "https://s.test/about/who-we-are"


def test_table_with_position_column_and_last_first_names():
    html = (
        "<table><tr><td>Staff Member</td><td>Position</td><td>&nbsp;</td></tr>"
        "<tr><td>Rivera, Jordan&nbsp;&nbsp;</td><td>3rd Grade</td><td>&nbsp;</td></tr>"
        "<tr><td>Okafor, Dana</td><td>Nurse</td><td></td></tr></table>"
    )
    people = staff_roster._parse_table_page(html)
    assert [(p["full_name"], p["title"]) for p in people] == [("Jordan Rivera", "3rd Grade"), ("Dana Okafor", "Nurse")]


def test_table_without_position_column_still_reads_first_column_as_title():
    html = "<table><tr><td>Grade</td><td>Staff Member</td></tr><tr><td>Kindergarten</td><td>Pat Lee</td></tr></table>"
    assert [(p["full_name"], p["title"]) for p in staff_roster._parse_table_page(html)] == [("Pat Lee", "Kindergarten")]
