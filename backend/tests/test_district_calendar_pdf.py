from services.district_calendar_pdf import build_items, compose_title, find_pdf_link
from services.school_today import classify_day


def test_finds_json_escaped_pdf_url_in_inline_script():
    html = '<script>{"src":"https:\\/\\/files.smartsites.parentsquare.com\\/13602\\/2026-27_etsd_district_calendar_82026.pdf"}</script>'
    assert find_pdf_link(html, "https://x.test/p") == "https://files.smartsites.parentsquare.com/13602/2026-27_etsd_district_calendar_82026.pdf"


def test_prefers_calendar_pdf_and_resolves_relative_href():
    html = '<a href="/f/handbook.pdf">h</a><a href="/f/district_calendar.pdf">c</a>'
    assert find_pdf_link(html, "https://x.test/p") == "https://x.test/f/district_calendar.pdf"
    assert find_pdf_link("<p>nothing</p>", "https://x.test/p") is None


def test_status_titles_classify_as_intended():
    # Printed "Student Two-Hour Delayed Opening/Teacher In-Service" must stay a delay, not a closure.
    assert classify_day([compose_title("delayed_opening", "Teacher In-Service")])[0] == "delayed"
    assert classify_day([compose_title("early_dismissal", "Parent/Teacher Conferences")])[0] == "early_dismissal"
    assert compose_title("early_dismissal", "Student Early Dismissal/Teacher In-Service (Primary Election Day)") == "Early Dismissal - Primary Election Day"
    assert compose_title("early_dismissal", "Student Early Dismissal") == "Early Dismissal"
    assert classify_day([compose_title("closed", "Yom Kippur")]) == ("closed", "Yom Kippur")
    assert classify_day([compose_title("other", "First Student Day")])[0] == "open"


def test_build_items_multi_day_end_is_exclusive_and_bad_dates_skipped():
    events = [
        {"start_date": "2026-11-26", "end_date": "2026-11-27", "kind": "closed", "subject": "Thanksgiving Recess", "printed": "Thu-Fri - Thanksgiving Recess (Schools Closed)"},
        {"start_date": "2026-09-02", "end_date": "2026-09-02", "kind": "other", "subject": "First Student Day", "printed": "Wed - First Student Day"},
        {"start_date": "garbage", "end_date": "garbage", "kind": "other", "subject": "x", "printed": "x"},
    ]
    wanted, skipped = build_items(events, "https://x/cal.pdf", "abc123")
    assert skipped == 1 and len(wanted) == 2
    thanks = next(f for f in wanted.values() if f["title"].startswith("Schools Closed"))
    assert thanks["start_date"].day == 26 and thanks["end_date"].day == 28
    assert all(uid.startswith("dcpdf:abc123:") for uid in wanted)
