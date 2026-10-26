from pathlib import Path

import pytest

from services.transportation import (
    late_bus_for_school,
    parse_bus_stop_change,
    parse_delay_policy,
    parse_late_bus,
    parse_lost_items,
    parse_main,
)

FIX = Path(__file__).parent / "fixtures" / "transportation"


def _load(name: str) -> str:
    return (FIX / f"{name}.html").read_text()


def test_main_page_office_and_contacts():
    m = parse_main(_load("main"))
    assert m["office_phone"] == "(856) 489-5851"
    assert m["office_fax"] == "(856) 489-5774"
    assert m["office_hours"] == "7:00 am - 4:30 pm daily"
    assert m["office_address"] == "Malberg Administration Building, 45 Ranoldo Terrace, Cherry Hill, NJ 08034-0391"
    names = {c["name"]: c for c in m["contacts"]}
    assert names["Linda King"]["title"] == "Transportation Supervisor"  # had a stray nbsp on the real page
    assert names["Linda King"]["email"] == "lking@chclc.org"
    assert len(m["contacts"]) == 6


def test_late_bus_contractors_and_routes():
    lb = parse_late_bus(_load("late_bus"))
    assert "courtesy buses" in lb["late_bus_policy"]
    by_name = {c["name"]: c for c in lb["late_bus_contractors"]}
    assert by_name["First Student - Berlin"]["phone"] == "(856) 753-0222"
    assert by_name["First Student - Berlin"]["routes"]["EAST"] == ["ELR-1", "ELR-2", "ELR-3", "ELR-4", "ELR-5", "ELR-6"]
    assert by_name["Hillman's Bus Service"]["routes"]["BECK"] == ["BLR-1", "BLR-2", "BLR-3"]


def test_late_bus_for_school_matches_by_name_and_is_none_for_elementary():
    contractors = parse_late_bus(_load("late_bus"))["late_bus_contractors"]
    assert late_bus_for_school(contractors, "Henry C. Beck Middle School", "Beck")["contractor"] == "Hillman's Bus Service"
    assert late_bus_for_school(contractors, "Cherry Hill High School East", None)["routes"][0] == "ELR-1"
    assert late_bus_for_school(contractors, "Bret Harte Elementary", "Bret Harte") is None
    assert late_bus_for_school(None, "Anything", None) is None


def test_policy_paragraphs():
    assert "20 minutes or more" in parse_delay_policy(_load("automated"))
    change = parse_bus_stop_change(_load("guidelines"), _load("change_request"), "https://www.chclc.org")
    assert "11:30am" in change["bus_stop_change_procedure"]
    assert "October 31st" in change["bus_stop_change_deadline"]
    assert change["bus_stop_change_form_url"] == "https://www.chclc.org/fs/pages/6557"
    assert "3 days" in parse_lost_items(_load("lost_items"))


@pytest.mark.anyio
async def test_fetch_page_retries_transient_scraper_failure(monkeypatch):
    import services.transportation as t

    calls = {"n": 0}

    async def flaky(url, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("502 Bad Gateway")
        return {"html": "<main id='fsPageContent'>ok</main>"}

    monkeypatch.setattr(t.scraper_client, "fetch_html", flaky)
    html = await t._fetch_page("https://example.org/x", attempts=3, backoff_s=0)
    assert html.endswith("ok</main>")
    assert calls["n"] == 2


@pytest.mark.anyio
async def test_fetch_page_gives_up_after_attempts(monkeypatch):
    import services.transportation as t

    async def always_bad(url, wait_for_selector=None, timeout_ms=15_000, block_assets=False):
        raise RuntimeError("502 Bad Gateway")

    monkeypatch.setattr(t.scraper_client, "fetch_html", always_bad)
    with pytest.raises(RuntimeError):
        await t._fetch_page("https://example.org/x", attempts=2, backoff_s=0)


def test_parsers_ignore_page_chrome_outside_fspagecontent():
    # The live fetch is the whole page; only #fsPageContent is the page's own
    # content. The footer's mission statement must never leak into a policy.
    html = (
        '<html><body><nav><p>Menu</p></nav>'
        '<main id="fsPageContent"><p>When notified in advance, delays of 20 minutes or more get an automated message.</p></main>'
        '<footer><p>Our Mission Statement: We shall provide all children with an education.</p><p>© Copyright 2024</p></footer>'
        '</body></html>'
    )
    text = parse_delay_policy(html)
    assert "20 minutes" in text
    assert "Mission Statement" not in text and "Copyright" not in text


def test_eschoolview_page_parses_office_staff_with_decoded_emails_and_sections():
    from services.transportation import _decode_cfemail, parse_eschoolview_page

    key = 0x42
    encoded = bytes([key]) + bytes(ord(c) ^ key for c in "a@b.org")
    assert _decode_cfemail(encoded.hex()) == "a@b.org"
    html = f"""<nav><a>Transportation</a></nav>
    <p>District Transportation Office</p><p>&nbsp;354 Mount Laurel Road &middot; Mount Laurel, NJ 08054</p>
    <p>&nbsp;Phone: (856) 778-6905 &middot; Fax: (856) 235-1440</p>
    <p>Our office hours are 6:00 am - 5:00 pm daily.</p>
    <p>Jo Doe&nbsp;-&nbsp;Transportation Supervisor<br><a><span data-cfemail="{encoded.hex()}">[email protected]</span></a></p>
    <p>CHANGE OF BUS STOP LOCATION</p><p>Only for safety reasons.</p>
    <p>AUTOMATED TEXT MESSAGES</p><p>Delays of 20 minutes or more get a text.</p>
    <p>BUS SAFETY</p><p>Drivers keep items for 3 days. The driver hands them in.</p>"""
    r = parse_eschoolview_page(html, "https://x.test/Transportation.aspx")
    assert (r["office_phone"], r["office_fax"], r["office_hours"]) == ("(856) 778-6905", "(856) 235-1440", "6:00 am - 5:00 pm daily")
    assert r["office_address"] == "354 Mount Laurel Road, Mount Laurel, NJ 08054"
    assert r["contacts"] == [{"name": "Jo Doe", "title": "Transportation Supervisor", "email": "a@b.org"}]
    assert r["delay_policy"] == "Delays of 20 minutes or more get a text."
    assert r["bus_stop_change_procedure"] == "Only for safety reasons."
    assert "3 days" in r["lost_items_policy"]


def test_edlio_pages_parse_phone_hours_staff_and_stop_change_rule():
    from services.transportation import parse_edlio_transportation

    def page(body):
        return f'<nav><a>Staff</a></nav><main id="content_main"><h1>x</h1>{body}</main>'

    info = page("<p>Hours of operation are 6:30 am to 4:30 pm, Monday through Friday.</p><p>Call the Transportation office at (609) 953-5841 ext 2.</p>")
    staff = page("<p>Staff</p><p>Staff</p><p>Ann Lee</p><p>Transportation Supervisor</p><p>ext. 1566</p><p>Bo Kim</p><p>ext. 1565</p><p>Guidelines</p>")
    guide = page(
        '<h3>Bus Stop Times</h3><p>Wait 10 minutes.</p><h3>Alternate Bus Stop Location</h3>'
        '<p>Complete the form by the first week of August.</p><p><a href="/files/alt.pdf">Childcare - Alternate Transportation Request</a></p><h3>Other</h3><p>x</p>'
    )
    r = parse_edlio_transportation(info, staff, guide, {"main": "https://x.test/i", "guidelines": "https://x.test/g"})
    assert (r["office_phone"], r["office_hours"]) == ("(609) 953-5841 ext. 2", "6:30 am to 4:30 pm, Monday through Friday")
    assert r["contacts"] == [
        {"name": "Ann Lee", "title": "Transportation Supervisor - ext. 1566", "email": None},
        {"name": "Bo Kim", "title": "ext. 1565", "email": None},
    ]
    assert r["bus_stop_change_procedure"].startswith("Complete the form")
    assert r["bus_stop_change_deadline"] == "first week of August"
    assert r["bus_stop_change_form_url"] == "https://x.test/files/alt.pdf"


# Single-page departments. Shapes copied from the real pages (Winslow,
# Burlington City and Camden County Technical on Educational Networks,
# Waterford on Finalsite); names, numbers and addresses are invented.

def _ednet(content: str, aside: str = "") -> str:
    return (
        '<html><body><nav><a href="/x">Transportation</a></nav>'
        f'<div id="en-content-wrapper"><div id="pageAsideWrapper">{aside}</div>'
        f'<div id="pageContentWrapper"><div id="enEditableDiv1">{content}</div></div></div>'
        '<footer><div class="enf-phone">P: (856) 555-0000</div></footer></body></html>'
    )


def test_ednet_department_reads_office_staff_and_activity_bus_rules():
    from services.transportation import missing_fields, parse_department_page

    main = _ednet(
        "<div><strong>Transportation Office of the Example Township School District</strong></div>"
        "<div><strong>30 Sample Road, Atco, New Jersey 08004</strong></div>"
        "<div><strong>Ms. Ann Lee, Director of Transportation</strong></div>"
        "<div><strong>Telephone: (856) 555-2850 x7610</strong></div>",
        '<a href="?pREC_ID=staff">Staff</a><a href="?pREC_ID=2">Transportation Regulations</a>',
    )
    staff = _ednet(
        '<table><tr class="dark"><td>Name</td><td>Position</td><td>Email</td></tr>'
        '<tr class="light staff-categoryStaffMember"><td><a href="?uREC_ID=1&type=u">Ms. Ann Lee</a></td>'
        '<td><span>Director of Transportation</span></td><td><a href="mailto:leea@example.org">leea@example.org</a></td></tr></table>'
        '<ul><li class="staff-categoryStaffMember"><a href="?uREC_ID=2&type=u"><dl><dt> Bo Kim</dt><dd>Dispatcher</dd></dl></a></li></ul>'
    )
    rules = _ednet(
        "<p>Contact Transportation: 856-555-2850 x7610</p><ul>"
        "<li>Students should be at the bus stop five (5) minutes before the school bus arrives.</li>"
        "<li>Student staying for any after-school activity must have a signed bus pass, provided by an advisor, in order to board any school bus.</li>"
        "</ul><p>Late Bus</p>"
    )
    r = parse_department_page({"main": main, "staff": staff, "guidelines": rules}, {"main": "https://x.test/t", "guidelines": "https://x.test/r"})
    assert r["office_phone"] == "(856) 555-2850 x7610"
    assert r["office_address"] == "30 Sample Road, Atco, New Jersey 08004"
    assert r["contacts"] == [
        {"name": "Ms. Ann Lee", "title": "Director of Transportation", "email": "leea@example.org"},
        {"name": "Bo Kim", "title": "Dispatcher", "email": None},
    ]
    # The rule about activity buses, not the "Late Bus" heading.
    assert r["late_bus_policy"] == "Student staying for any after-school activity must have a signed bus pass, provided by an advisor, in order to board any school bus."
    assert (r["main_url"], r["guidelines_url"], r["daily_buses_note"]) == ("https://x.test/t", "https://x.test/r", None)
    assert missing_fields("department_page", r) == []


def test_finalsite_single_page_reads_hours_after_hours_line_mailbox_and_stop_form():
    from services.transportation import parse_department_page

    html = (
        '<header><p>Phone: (856) 555-1111</p></header><main id="fsPageContent">'
        "<p>All buses are equipped with video. These recordings may be used for investigations.</p>"
        "<p>Hours of Transportation Office are 8am - 4pm.  Any transportation emergencies outside of office hours "
        "can be directed to First Student at (856)555-0222.</p>"
        "<p><strong>856-555-8293 x5041</strong> - Transportation Office</p>"
        "<p>Email: <strong>transportation@example.org</strong></p>"
        '<p><a href="https://forms.example/report">Report a School Bus Violation<span class="fsStyleSROnly">(opens in new window)</span></a></p>'
        '<p><a href="https://forms.example/sitter">2026-2027 Sitter Stop Request</a></p>'
        '<p><a href="https://forms.example/form/252615042372046">Link</a> https://forms.example/form/252615042372046</p>'
        "</main><footer><p>Phone: (856) 555-9999</p></footer>"
    )
    r = parse_department_page({"main": html}, {"main": "https://x.test/transportation"})
    assert r["office_phone"] == "856-555-8293 x5041"  # not the First Student line, the footer, or the form's digits
    assert r["office_hours"] == "8am - 4pm"
    assert r["delay_policy"] == "Any transportation emergencies outside of office hours can be directed to First Student at (856)555-0222."
    assert (r["office_email"], r["contacts"]) == ("transportation@example.org", [])
    assert r["bus_stop_change_form_url"] == "https://forms.example/sitter"


def test_vocational_school_whose_daily_buses_are_the_home_districts_has_no_office_to_call():
    from services.transportation import missing_fields, parse_department_page

    main = _ednet(
        '<p class="MsoNormal"><b><u><span>Daily transportation to and from school</span></u></b><span> is provided by the '
        "student’s sending school district.  Please contact the transportation department of your local school district "
        "with questions.</span><br/></p><p class=\"MsoNormal\"><span>​</span></p>"
        '<p class="MsoNormal"><b><u><span>Transportation home from after-school activities</span></u></b><span> is provided by '
        "the school. For questions about 21<sup>st</sup> Century programs, please call the following number during the times noted below:</span></p>"
        "<p><strong><u>GTC/PC</u></strong></p><p><span>7:00 AM – 3:00 PM 856-555-7000, x5202 or x5297</span></p><p>Unrelated closing line.</p>"
    )
    r = parse_department_page({"main": main}, {"main": "https://x.test/t"})
    assert r["daily_buses_note"].startswith("Daily transportation to and from school is provided by the student’s sending school district.")
    assert r["office_phone"] is None
    assert r["late_bus_policy"] == (
        "Transportation home from after-school activities is provided by the school. For questions about 21st Century programs, "
        "please call the following number during the times noted below: GTC/PC 7:00 AM – 3:00 PM 856-555-7000, x5202 or x5297"
    )
    assert missing_fields("department_page", r) == []


def test_department_page_reads_a_contact_sentence_and_keeps_the_phone_beside_a_walking_district_note():
    from services.transportation import missing_fields, parse_department_page

    monroe = (
        '<main><p>Our hours are Monday through Friday from 7:00AM - 4:30PM during the school year.</p>'
        "<p>If at any time you need assistance, please contact the transportation department at 856-555-6400 EXT. #3 "
        "or via email at Transportation@example.org.</p></main>"
    )
    r = parse_department_page({"main": monroe}, {"main": "https://x.test/t"})
    assert r["office_hours"] == "Monday through Friday from 7:00AM - 4:30PM during the school year"
    assert r["office_phone"] == "856-555-6400 EXT. #3"
    assert r["office_email"] == "Transportation@example.org"

    walking = _ednet(
        "<p>Pat Doe</p><p>Transportation Coordinator</p><p>Phone: (856) 555-0123 Ext. 225</p>"
        "<p>Since no home is that far from school, the district is not required to transport most students to school.</p>"
    )
    r = parse_department_page({"main": walking}, {"main": "https://x.test/t"})
    assert r["daily_buses_note"].endswith("not required to transport most students to school.")
    assert r["office_phone"] == "(856) 555-0123 Ext. 225"
    assert missing_fields("department_page", r) == []


def test_page_without_a_content_container_yields_nothing_rather_than_its_footer():
    from services.transportation import missing_fields, parse_department_page

    html = (
        '<html><body><div id="app"></div><div role="main"></div><footer><p>Example Township Public Schools 440 Main Rd. '
        "Phone: (609) 555-8600</p><p>HIB Information Late bus questions? Contact Us</p></footer></body></html>"
    )
    r = parse_department_page({"main": html}, {"main": "https://x.test/page/transportation"})
    assert all(not r[k] for k in ("office_phone", "delay_policy", "late_bus_policy", "contacts", "daily_buses_note"))
    assert missing_fields("department_page", r) == ["office_phone"]


def test_faq_page_skips_bus_company_numbers_and_reads_the_answers():
    from services.transportation import missing_fields, parse_department_page

    # Voorhees and Eastern Regional: a FAQ, the office reached by email, and a list of bus companies' numbers.
    html = (
        '<main id="fsPageContent"><h2>FREQUENTLY ASKED QUESTIONS</h2>'
        "<p>Where is the bus stop?</p><p>All stops are in the parent portal. Email the coordinator with questions.</p>"
        "<p>The morning bus is late. What should I do?</p><p>Call the bus company regarding the status of the bus.</p>"
        "<p>My student took the late bus from the middle school and they\u2019re not home yet. What should I do?</p>"
        "<p>All of our late buses (3:30pm and 4:15pm) are operated by Example Bus Co. It can be reached at 856-555-3632.</p>"
        "<p>How do I retrieve a lost item?</p><p>If your child leaves an item on the school bus, they should check with the driver during their next ride.</p>"
        "<p>An automated message is sent when the district is notified of a delay of more than 15 minutes.</p>"
        "<p>I have other questions. Who can I contact?</p>"
        "<p>The Transportation Department in Example Township is open from 8:00am to 4:00pm. The best means of contact is via email to coord@example.org.</p>"
        "<p>If you are unsure who operates your child\u2019s bus, please contact the Transportation Department.</p>"
        "<p>First Student, Berlin Depot 856-555-0222</p><p>Example Bus Service 856-555-1123</p><p>T&amp;L Transportation 856-555-6609</p></main>"
    )
    r = parse_department_page({"main": html}, {"main": "https://x.test/t"})
    assert r["office_phone"] is None  # every number on the page is a bus company's
    assert (r["office_email"], r["office_hours"]) == ("coord@example.org", "8:00am to 4:00pm")
    assert r["delay_policy"] == (
        "Call the bus company regarding the status of the bus. "
        "An automated message is sent when the district is notified of a delay of more than 15 minutes."
    )
    assert r["late_bus_policy"].startswith("All of our late buses (3:30pm and 4:15pm)")
    assert r["lost_items_policy"].startswith("If your child leaves an item on the school bus")
    assert missing_fields("department_page", r) == []  # reachable by email


def test_label_lines_and_a_phone_under_a_staff_title():
    from services.transportation import parse_department_page

    # Delran (Presence, `.pageContent`): each value on the line under its label.
    delran = (
        '<div class="mainContent"><div class="pageContent"><h2>Transportation &amp; Support Services Department</h2>'
        "<p>Address</p><p>22 Sample Road, Delran, NJ 08075</p><p>Phone</p><p>856-555-1553</p><p>Fax</p><p>856-555-7750</p>"
        "<p>Hours</p><p>7:00 AM \u2013 4:00 PM</p><p>Before or after hours, you may reach First Student directly at 856-555-8653.</p>"
        '<a href="/sitter_stop_requests/">Sitter Stop Requests 2026-27</a></div></div>'
    )
    r = parse_department_page({"main": delran}, {"main": "https://x.test/t"})
    assert (r["office_phone"], r["office_fax"], r["office_hours"]) == ("856-555-1553", "856-555-7750", "7:00 AM \u2013 4:00 PM")
    assert r["office_address"] == "22 Sample Road, Delran, NJ 08075"
    assert r["delay_policy"] == "Before or after hours, you may reach First Student directly at 856-555-8653."
    assert r["bus_stop_change_form_url"] == "https://x.test/sitter_stop_requests/"

    # Cinnaminson (Smart Sites): name, title, a "Contact" button, then the number.
    cinnaminson = (
        "<main><p>Transportation Department Staff</p><p>Ann Lee</p><p>Director of Transportation</p><p>Contact Ann</p>"
        '<p>(856) 555-8812</p><p>Fax: (856) 555-3875</p><a href="/alternate">Request for Alternate Transportation</a><ul>'
        "<li>Students who ride the late bus, or are provided transportation by the school to attend an event will adhere to these same rules.</li></ul></main>"
    )
    r = parse_department_page({"main": cinnaminson}, {"main": "https://x.test/t"})
    assert (r["office_phone"], r["office_fax"]) == ("(856) 555-8812", "(856) 555-3875")
    assert r["late_bus_policy"] is None  # a rule pointing back at a list it doesn't show
    assert r["bus_stop_change_form_url"] == "https://x.test/alternate"


@pytest.mark.anyio
async def test_discover_reads_cherry_hills_tree_only_when_the_main_page_links_it(monkeypatch):
    import services.transportation as t

    fetched: list[str] = []
    single = '<main id="fsPageContent"><p>(856) 555-8293 - Transportation Office</p></main>'
    tree = _load("main") + '<a href="/departments/transportation/late-bus-information">Late Bus</a>'

    async def fake_fetch(url):
        fetched.append(url)
        if url.endswith("/departments/transportation"):
            return tree
        if url.endswith("/our-district/transportation"):
            return single
        return _load({"late-bus-information": "late_bus", "automated-messages": "automated", "bus-guidelines": "guidelines",
                      "change-request-guidelines-and-form": "change_request", "lost-items": "lost_items"}[url.rsplit("/", 1)[1]])

    monkeypatch.setattr(t, "_fetch_page", fake_fetch)
    reader, info = await t.discover_transportation("https://one.test/our-district/transportation", "https://one.test")
    assert (reader, info["office_phone"], fetched) == ("department_page", "(856) 555-8293", ["https://one.test/our-district/transportation"])
    assert info["daily_buses_note"] is None

    fetched.clear()
    reader, info = await t.discover_transportation("https://www.chclc.org/departments/transportation", "https://www.chclc.org")
    assert reader == "finalsite_tree" and len(fetched) == 6
    assert info["office_phone"] == "(856) 489-5851" and info["late_bus_contractors"]
    assert "daily_buses_note" in info


@pytest.mark.anyio
async def test_school_and_district_routes_hide_a_department_with_nothing_to_act_on():
    import os
    import uuid

    os.environ.setdefault("JWT_SECRET", "test-secret")
    from httpx import ASGITransport, AsyncClient

    import database
    from main import app
    from models import District, DistrictTransportation, School

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        district = District(name=f"Bus District {tag}", state="NJ")
        db.add(district)
        await db.flush()
        db.add(School(name=f"Bus School {tag}", slug=f"bus-school-{tag}", district_id=district.id, school_type="high"))
        row = DistrictTransportation(district_id=district.id, delay_policy="The page you have entered does not exist", main_url="https://x.test/t",
                                     contacts=[{"name": "Transportation office", "title": None, "email": "transportation@x.test"}])
        db.add(row)
        await db.commit()
        district_id = district.id

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get(f"/schools/bus-school-{tag}/transportation")).json() is None
        assert (await client.get(f"/districts/{district_id}/transportation")).json() is None

        async with database.SessionLocal() as db:
            stored = await db.get(DistrictTransportation, row.id)
            stored.daily_buses_note = "Daily transportation is provided by the student's sending school district."
            await db.commit()
        body = (await client.get(f"/schools/bus-school-{tag}/transportation")).json()
        assert body["district"]["daily_buses_note"].startswith("Daily transportation")
        assert body["district"]["office_email"] is None
        assert body["late_bus"] is None
        assert body["district"]["contacts"] == [{"name": "Transportation office", "title": None, "email": "transportation@x.test"}]
        assert (await client.get(f"/districts/{district_id}/transportation")).json()["daily_buses_note"].startswith("Daily")

        # An office reached only by email counts too (Voorhees).
        async with database.SessionLocal() as db:
            stored = await db.get(DistrictTransportation, row.id)
            stored.daily_buses_note, stored.office_email = None, "office@x.test"
            await db.commit()
        assert (await client.get(f"/schools/bus-school-{tag}/transportation")).json()["district"]["office_email"] == "office@x.test"
