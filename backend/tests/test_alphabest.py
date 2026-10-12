from pathlib import Path

from services.alphabest import format_phone, parse_location_page

URL = "https://www.alphabest.org/gloucesternj/"


def test_location_page_fills_the_sacc_block():
    html = (Path(__file__).parent / "fixtures" / "alphabest_location.html").read_text()
    block = parse_location_page(html, URL)
    assert block["am_hours"] == "7:00 AM - start of school"
    assert block["pm_hours"] == "Dismissal - 6:00 PM"
    assert block["site_phone"] == "(856) 301-0891"
    assert block["handbook_url"] == URL
    notes = block["closures_notes"]
    assert "Run by AlphaBEST" in notes
    assert "Rates (2026/2027)" in notes
    assert "5 days per week $360.00 per month" in notes
    assert "Hosted at Cold Springs School" in notes
    assert "kangarootime.com" in notes


def test_phone_format_and_missing_pieces():
    assert format_phone("856.3010891") == "(856) 301-0891"
    assert format_phone("call us") is None
    assert parse_location_page("<html></html>", URL)["am_hours"] is None
