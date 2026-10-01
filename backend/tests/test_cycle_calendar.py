import datetime
import pathlib

from services.cycle_calendar import parse_cycle_pdf

FIXTURE = pathlib.Path(__file__).parent / "fixtures" / "medford_lakes_cycle_2026_27.pdf"


def _days():
    parsed = parse_cycle_pdf(FIXTURE.read_bytes())
    return parsed, {d["date"]: d for d in parsed["days"]}


def test_title_year_and_cycle_length():
    parsed, _ = _days()
    assert (parsed["academic_year"], parsed["cycle_length"]) == ("2026-2027", 6)


def test_both_month_columns_are_read_and_dates_pair_with_their_own_digit():
    _, days = _days()
    # Left column (Sep) and right column (Feb) of the same grid rows.
    assert days["2026-09-01"]["day_number"] == 1
    assert days["2026-09-08"]["day_number"] == 5  # after Labor Day (X)
    assert days["2027-02-01"]["day_number"] == 5
    assert days["2027-06-11"]["day_number"] == 6


def test_x_cells_are_closed_with_no_day_number():
    _, days = _days()
    for d in ("2026-09-07", "2026-09-21", "2026-11-26", "2027-03-29", "2027-05-31"):
        assert days[d] == {"date": d, "day_number": None, "closed": True}


def test_every_school_day_is_a_weekday_and_the_cycle_never_breaks():
    parsed, _ = _days()
    school = [d for d in parsed["days"] if not d["closed"]]
    assert len(school) == 180
    assert all(datetime.date.fromisoformat(d["date"]).weekday() < 5 for d in parsed["days"])
    for prev, cur in zip(school, school[1:]):
        assert cur["day_number"] == prev["day_number"] % 6 + 1


def test_pick_cycle_pdf_prefers_newest_year_and_ignores_other_documents():
    from scheduler.jobs.hs_rotation_scan import pick_cycle_pdf

    docs = [
        {"doc_type": "letter_day_schedule", "title": "2026-2027 6 Day Cycle Calendar", "url": "https://x/a-2026.pdf", "academic_year": "2026-2027"},
        {"doc_type": "letter_day_schedule", "title": "2027-2028 6 Day Cycle Calendar", "url": "https://x/a-2027.pdf", "academic_year": "2027-2028"},
        {"doc_type": "letter_day_schedule", "title": "What Day is It?", "url": "https://drive.google.com/file/d/1/view", "academic_year": None},
        {"doc_type": "bell_schedule", "title": "Bell cycle", "url": "https://x/bell.pdf", "academic_year": "2030-2031"},
    ]
    assert pick_cycle_pdf(docs) == "https://x/a-2027.pdf"
    assert pick_cycle_pdf([]) is None
