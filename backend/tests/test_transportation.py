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
