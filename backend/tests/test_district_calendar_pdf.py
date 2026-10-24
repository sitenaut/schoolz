import pytest

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


def test_drive_calendar_link_and_base_href():
    html = (
        '<base href="https://www.clemsd.org/"><a href="documents/Forms/Use-of-facilities.pdf">Use</a>'
        '2026-27 Calendar (Approved 2.12.26) - <a href="https://drive.google.com/file/d/1Pv9wzE63-EsCy9q4kHrpE3aKGecJxjoh/view?usp=sharing">English</a>'
    )
    assert find_pdf_link(html, "https://www.clemsd.org/District-Info/District-Calendar/index.html") == (
        "https://drive.google.com/uc?export=download&id=1Pv9wzE63-EsCy9q4kHrpE3aKGecJxjoh"
    )
    only_pdf = '<base href="https://www.clemsd.org/"><a href="documents/x.pdf">x</a>'
    assert find_pdf_link(only_pdf, "https://www.clemsd.org/a/b/index.html") == "https://www.clemsd.org/documents/x.pdf"


def test_finalsite_resource_manager_calendar_beats_a_direct_school_pdf():
    html = (
        '<a data-file-name="2026-2027CalendarUpdated9-15-26.pdf" data-resource-uuid="202275b0" '
        'href="/fs/resource-manager/view/202275b0-e22f" target="_blank">2026-2027 Pennsauken Public Schools Calendar</a>'
        '<a class="fsResourceLink" href="https://resources.finalsite.net/images/v1/pennsaukennet/x/CarsonCalendarforSept2026.pdf">Carson</a>'
    )
    assert find_pdf_link(html, "https://www.pennsauken.net/calendars") == "https://www.pennsauken.net/fs/resource-manager/view/202275b0-e22f"


def test_drive_calendar_label_must_sit_against_the_link():
    nav = '<a href="/cal">Calendar</a> <a href="https://drive.google.com/file/d/AAAAAAAAAAAAAAAAAAAA/view">Referral Services</a>'
    assert find_pdf_link(nav, "https://x.test/") is None


def test_find_pdf_link_prefers_the_school_year_calendar_over_a_monthly_one():
    html = (
        '<a href="/wp-content/uploads/2026-10-Calendar.pdf">Monthly Calendar</a>'
        '<a href="/wp-content/uploads/school-calendar-2026-2027-with-activities.pdf">2026.2027 Calendar</a>'
    )
    assert find_pdf_link(html, "https://x.test/") == "https://x.test/wp-content/uploads/school-calendar-2026-2027-with-activities.pdf"


@pytest.mark.anyio
async def test_a_cut_off_read_raises_instead_of_replacing_the_stored_rows(monkeypatch):
    from types import SimpleNamespace

    from services import district_calendar_pdf

    class _Messages:
        async def create(self, **kwargs):
            partial = {"events": [{"date": "2026-09-07", "kind": "closed", "subject": "Labor Day"}]}
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=partial)], stop_reason="max_tokens", usage=None)

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(district_calendar_pdf, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(district_calendar_pdf, "AsyncAnthropic", _Client)
    with pytest.raises(RuntimeError):
        await district_calendar_pdf.extract_events(b"%PDF-1.4 not a real calendar")
