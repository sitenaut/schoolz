from pathlib import Path

from services.special_events import _find_calendar_pdf_url

_FIXTURE = Path(__file__).parent / "fixtures" / "special_events" / "chesterbrook_calendars_menu_2026_09.html"


def test_finds_the_special_events_calendar_pdf_on_the_real_page():
    html = _FIXTURE.read_text()
    url = _find_calendar_pdf_url(html)
    assert url == "https://www.chesterbrookacademy.com/wp-content/uploads/sites/2/2026/08/September-2026-Special-Events-Calendar.pdf"


def test_ignores_the_other_pdf_links_on_the_page():
    # The same page also links a lunch menu and a newsletter PDF for the
    # month - neither should be picked up as the special-events calendar.
    html = """
    <a href="https://example.com/wp-content/uploads/2026/09/September-2026-Lunch-Menu.pdf">Lunch Menu</a>
    <a href="https://example.com/wp-content/uploads/2026/09/September-2026-Newsletter.pdf">Newsletter</a>
    """
    assert _find_calendar_pdf_url(html) is None


def test_no_calendar_posted_yet_returns_none():
    assert _find_calendar_pdf_url("<html><body>no pdfs here</body></html>") is None
