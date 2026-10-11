from pathlib import Path

from services import district_calendar_pdf as svc

FIX = Path(__file__).parent / "fixtures"


def _blocks():
    text = svc.layout_text_by_month((FIX / "gateway_calendar_2026_27.pdf").read_bytes())
    assert text
    return {b.split(":\n")[0]: b.split(":\n")[1].splitlines() for b in text.split("\n\n")}


def test_two_column_year_grid_puts_each_entry_under_its_own_month():
    """Gateway's calendar prints July-December down the left and January-June
    down the right, each month's list beside its grid. The model read the page
    as a whole and moved right-column entries a month early (Spring Break in
    February, Memorial Day closing April 28 to May 31)."""
    blocks = _blocks()
    assert list(blocks) == [
        "JULY 2026", "AUGUST 2026", "SEPTEMBER 2026", "OCTOBER 2026", "NOVEMBER 2026", "DECEMBER 2026",
        "JANUARY 2027", "FEBRUARY 2027", "MARCH 2027", "APRIL 2027", "MAY 2027", "JUNE 2027",
    ]
    assert blocks["MARCH 2027"] == ["25 Noon Dismissal/In-Service", "26-31 Closed - Spring Break"]
    assert blocks["APRIL 2027"][:2] == ["1-2 Closed - Spring Break", "11-16 Senior Trip to Orlando, FL"]
    assert blocks["MAY 2027"] == ["27 Prom/ Noon Dismissal (No lunch) Staff In-Service", "28-31 Closed - Memorial Day"]
    assert blocks["OCTOBER 2026"] == ["9 Full Day In-Service", "12 Closed - Columbus Day"]
    assert blocks["FEBRUARY 2027"] == ["12 Full Day In-Service", "15 Closed - President’s Day"]


def test_notes_and_key_under_the_grid_are_not_attached_to_entries():
    blocks = _blocks()
    assert blocks["DECEMBER 2026"][-1] == "24-31 Closed - Winter Break"
    assert blocks["JUNE 2027"][-1] == "25 Summer Hours - Closed"
    assert not any("Student Days" in line or "Teacher Days" in line for lines in blocks.values() for line in lines)


def test_other_pdfs_are_left_to_the_plain_read():
    assert svc.layout_text_by_month(b"not a pdf") is None
