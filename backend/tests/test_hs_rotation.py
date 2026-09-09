from pathlib import Path

from services.hs_rotation import find_pdf_link, parse_rotation_pdf

FIXTURE = Path(__file__).parent / "fixtures" / "hs_day_rotation_2026_27.pdf"


def test_parse_real_2026_27_rotation_pdf():
    parsed = parse_rotation_pdf(FIXTURE.read_bytes())
    assert parsed["academic_year"] == "2026-2027"
    assert parsed["blocks"][1] == ["A", "B", "C", "E", "F", "G"]
    assert parsed["blocks"][6] == ["C", "D", "G", "H"]
    by_date = {d["date"]: d for d in parsed["days"]}

    # Spot checks against the sheet (and East's own Sept calendar: Sep 8 = Day 3).
    assert by_date["2026-09-08"]["day_number"] == 3
    assert by_date["2026-09-03"] == {"date": "2026-09-03", "day_number": 1, "cycle": 1, "early_dismissal": False, "closed": False, "note": "1- Cycle 1"}
    assert by_date["2026-09-07"]["closed"] is True and by_date["2026-09-07"]["day_number"] is None
    assert by_date["2026-11-25"]["day_number"] == 1 and by_date["2026-11-25"]["early_dismissal"] is True and by_date["2026-11-25"]["cycle"] == 10
    assert by_date["2026-10-29"]["day_number"] is None and by_date["2026-10-29"]["early_dismissal"] is True  # PSAT day
    # Column assignment across the page: January is the third column, June sits under May on page 2.
    assert by_date["2027-01-12"]["day_number"] == 1 and by_date["2027-01-12"]["cycle"] == 14
    assert by_date["2027-06-17"]["day_number"] == 4 and by_date["2027-06-17"]["early_dismissal"] is True
    assert by_date["2027-03-24"]["day_number"] == 3 and by_date["2027-03-24"]["early_dismissal"] is True
    # Every school day Sep 2026 - Jun 2027 lands in exactly one month; no leakage into the wrong year.
    assert min(by_date) == "2026-09-02" and max(by_date) == "2027-06-18"
    assert sum(1 for d in parsed["days"] if d["day_number"]) > 150


def test_find_pdf_link_scoped_to_page_content():
    html = '<nav><a href="/footer.pdf">x</a></nav><main id="fsPageContent"><a href="/files/DayRotation.pdf">here</a></main>'
    assert find_pdf_link(html, "https://west.chclc.org/x") == "https://west.chclc.org/x/files/DayRotation.pdf"
    assert find_pdf_link("<main id='fsPageContent'><p>nothing</p></main>", "https://a") is None
