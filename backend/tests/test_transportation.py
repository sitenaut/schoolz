from pathlib import Path

import pytest

from services.transportation import late_bus_for_school, parse_bus_stop_change, parse_delay_policy, parse_late_bus, parse_lost_items, parse_main

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

    async def flaky(url, wait_for_selector=None, timeout_ms=15_000):
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

    async def always_bad(url, wait_for_selector=None, timeout_ms=15_000):
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
