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


def test_faculty_list_nav_link_is_a_directory():
    """National Park's Finalsite nav calls its directory "Faculty List"."""
    home = '<a href="/school-information/faculty-list">Faculty List</a><a href="/athletics">Athletics</a>'
    assert staff_roster.find_directory_links(home, "https://www.npelem.com") == ["https://www.npelem.com/school-information/faculty-list"]


def test_json_directory_reads_name_title_and_extension_and_skips_blank_rows():
    """Westville's directory feed: no emails, the phone is an extension, and
    the list is padded with empty rows."""
    rows = [
        {"name": "Pat Teacher", "title": "First Grade", "phone": 117},
        {"name": "Sam Office", "title": "Business Administrator", "phone": "856-848-8203"},
        {"name": "No Phone", "title": "Aide", "phone": ""},
        {"name": "", "title": "", "phone": ""},
    ]
    people = staff_roster.parse_json_directory(rows)
    assert [(p["full_name"], p["title"], p["phone"], p["email"]) for p in people] == [
        ("Pat Teacher", "First Grade", "ext. 117", None),
        ("Sam Office", "Business Administrator", "856-848-8203", None),
        ("No Phone", "Aide", None, None),
    ]
    assert staff_roster.parse_json_directory({"not": "a list"}) == []


def test_json_directory_ids_fit_the_column_for_long_titles():
    long_title = "Principal / Educational Stability Liaison / McKinney Vento Specialist"
    [person] = staff_roster.parse_json_directory([{"name": "Pat Principal", "title": long_title, "phone": 117}])
    assert len(person["constituent_id"]) <= 64


_WENONAH = """
<ul class="pc-list">
 <li><h5>Chief School Administrator</h5>
  <a href="mailto:kh@example.org" title="Email">Ms. Kristine Height</a><br> 856-468-6000 ext. 100</li>
 <li><h5>Interim Business Administrator</h5>
  <a href="mj@example.org">Mrs. Michelle Jankauskas</a></li>
 <li><h5>Board Secretary</h5><a href="mailto:lj@example.org"><span>Ms. Lori Jones</span></a></li>
 <li><h5>Office Staff</h5><a href="mailto:lj@example.org">Ms. Lori Jones</a></li>
 <li><h5>3rd Grade</h5>
  <a href="https://app.oncoursesystems.com/school/webpage/1">Ms. Class Page</a></li>
 <li><h5>Special Services</h5><ul><li><a href="mailto:cst@example.org"><span>Child Study Team</span></a></li>
  <li><h6>Speech Pathologist</h6><a href="mailto:tt@example.org">Mrs. Tara Timms</a></li></ul></li>
</ul>
"""


def test_pc_list_page_reads_roles_emails_and_skips_class_pages_and_shared_inboxes():
    people = {p["full_name"]: p for p in staff_roster._parse_pc_list_page(_WENONAH)}
    assert set(people) == {"Kristine Height", "Michelle Jankauskas", "Lori Jones", "Class Page", "Tara Timms"}
    assert people["Kristine Height"]["email"] == "kh@example.org"
    assert people["Kristine Height"]["phone"] == "856-468-6000 ext. 100"
    assert people["Michelle Jankauskas"]["email"] == "mj@example.org"  # "mailto:" left off in the page
    assert people["Class Page"]["email"] is None and people["Class Page"]["title"] == "3rd Grade"
    assert people["Lori Jones"]["title"] == "Board Secretary / Office Staff"
    assert people["Tara Timms"]["title"] == "Speech Pathologist"


_SJA = """
<div class="siteorigin-widget-tinymce textwidget"><p style="text-align: center;">Sr. Patricia Pycik, SSJ<br />
School Principal<br />
<a href="mailto:p.pycik@stjoansk-8.org">p.pycik@stjoansk-8.org</a></p></div>
<div class="siteorigin-widget-tinymce textwidget"><p>&nbsp;</p><p style="text-align: center;">Kori Budzitowski<br />
Marketing &amp; Admissions<br />
<a href="mailto:k.budzitowski@stjoansk-8.org" target="_blank">k.budzitowski@stjoansk-8.org</a></p></div>
<div class="siteorigin-widget-tinymce textwidget"><p style="text-align: center;">Suzanne Rottler<br />
1A<br />
<a href="mailto:s.rottler@stjoansk-8.org">s.rottler@stjoansk-8.org</a></p></div>
<div class="siteorigin-widget-tinymce textwidget"><p style="text-align: center;">Ellen Nettleton</p><p>KA</p><p><a href="mailto:e.nettleton@stjoansk-8.org">e.nettleton@stjoansk-8.org</a></p></div>
<div class="siteorigin-widget-tinymce textwidget"><p>&nbsp;</p><p>Becky Lemanowicz<br />5B<br />b.lemanowicz@stjoansk-8.org</p></div>
<div class="siteorigin-widget-tinymce textwidget"><p>Ciara Rogovich<br />3B<br /><a href="mailto:j.relovsky@stjoansk-8.org">c.rogovich@stjoansk-8.org</a></p></div>
"""


def test_mailto_card_page_reads_name_title_and_email():
    people = {p["full_name"]: p for p in staff_roster._parse_mailto_card_page(_SJA)}
    assert people["Sr. Patricia Pycik, SSJ"]["title"] == "School Principal"
    assert people["Kori Budzitowski"]["title"] == "Marketing & Admissions"
    assert people["Suzanne Rottler"]["email"] == "s.rottler@stjoansk-8.org"
    assert people["Ellen Nettleton"]["title"] == "KA"
    assert people["Becky Lemanowicz"]["email"] == "b.lemanowicz@stjoansk-8.org"
    assert people["Ciara Rogovich"]["email"] == "c.rogovich@stjoansk-8.org"  # the displayed address, not the link's
    assert len(people) == 6


def test_elementor_staff_wrap_cards_are_parsed():
    # Riverton's /staff-directory/ layout (names here are made up).
    html = """<div class="staff_row">
      <div class="single_staff"><div class="staff_wrap"><h5>Ms. Example</h5>
        <div class="staff_designation">School Nurse</div>
        <div class="contact_numbers"><span class="phone_number">Phone: <a href="tel:856-555-0100">856-555-0100</a></span>
        <span class="phone_number">Ext. 108</span></div>
        <div class="email_address">Email: <a href="mailto:Nurse@example.org">Nurse@example.org</a></div></div></div>
      <div class="single_staff"><div class="staff_wrap"><h5>Mr. Sample</h5>
        <div class="staff_designation">Middle school social studies</div></div></div>
    </div>"""
    people = {p["full_name"]: p for p in staff_roster._parse_staff_wrap_page(html)}
    assert people["Ms. Example"]["title"] == "School Nurse" and people["Ms. Example"]["email"] == "nurse@example.org"
    assert people["Mr. Sample"]["email"] is None


def test_ednet_table_rows_without_profile_links_are_parsed():
    # Deptford's elementary sites (names here are made up).
    html = """<div class="staff-category"><table><caption><div><h1>Administration</h1></div></caption><tbody>
      <tr class="light staff-categoryStaffMember"><td data-label="Name :"><span> Ms. Example </span></td>
      <td data-label="Position :"><span>Principal</span></td></tr>
      <tr class="light staff-categoryStaffMember"><td data-label="Name :"><span> Mr. Sample </span></td>
      <td data-label="Position :"><span>School Nurse</span></td></tr></tbody></table></div>"""
    people = {p["full_name"]: p for p in staff_roster._parse_ednet_page(html)}
    assert people["Ms. Example"]["title"] == "Principal" and people["Ms. Example"]["department"] == "Administration"
    assert people["Mr. Sample"]["constituent_id"] != people["Ms. Example"]["constituent_id"]


def test_cs_table_contact_name_and_job_title_columns():
    # Paulsboro's WordPress /staff/ (names here are made up).
    html = """<table class="table cs-table"><thead><tr><th scope="col">Contact Name</th><th scope="col">Job Title</th></tr></thead>
      <tbody><tr><th scope="row">Example, Pat</th><td>School Nurse</td></tr>
      <tr><th scope="row">Sample, Lee</th><td>Principal</td></tr></tbody></table>"""
    people = {p["full_name"]: p["title"] for p in staff_roster._parse_table_page(html)}
    assert people == {"Pat Example": "School Nurse", "Lee Sample": "Principal"}
