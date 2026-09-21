from datetime import date
from types import SimpleNamespace

from services.kids_schedule import build_day, courses_for, term_for
from tests.test_bell_schedule import EAST


def _row(period, course, term="FY", days="123456"):
    return SimpleNamespace(period=period, course_name=course, term=term, days=days, teacher="T", room="R1")


LIST = [
    _row("A", "GEOMETRY"),
    _row("C", "COOKING", "S1"),
    _row("D", "PHILOSOPHY", "S1"),
    _row("D", "PHYS ED", "S2"),
    _row("G", "GERMAN"),
    _row("H", "HEALTH", "S1"),
    _row("L1", "Homeroom", days="135"),
    _row("L1", "Homeroom B", days="246"),
    _row("L2", "LUNCH/BREAK 2"),
]
MPS = [
    SimpleNamespace(label="MP1", start_date="2026-09-02", end_date="2026-11-10"),
    SimpleNamespace(label="MP2", start_date="2026-11-11", end_date="2027-01-27"),
    SimpleNamespace(label="MP3", start_date="2027-01-28", end_date="2027-04-08"),
    SimpleNamespace(label="MP4", start_date="2027-04-09", end_date="2027-06-17"),
]


def test_term_for_uses_the_students_marking_periods():
    assert term_for(date(2026, 12, 1), MPS) == "S1"
    assert term_for(date(2027, 1, 28), MPS) == "S2"
    assert term_for(date(2026, 12, 1), []) is None


def test_courses_for_picks_the_semester_and_never_guesses_without_one():
    assert [r.course_name for r in courses_for("D", 6, "S2", LIST)] == ["PHYS ED"]
    assert [r.course_name for r in courses_for("D", 6, None, LIST)] == ["PHILOSOPHY", "PHYS ED"]
    assert [r.course_name for r in courses_for("L1", 6, "S1", LIST)] == ["Homeroom B"]


def test_build_day_long_block_fall_day():
    day = build_day(date(2026, 9, 22), "open", "Day 6", ["C", "D", "G", "H"], EAST, LIST, "S1")
    assert day["long_blocks"] and day["timed"]
    assert [(b["name"], b["start_label"], b["course_name"]) for b in day["blocks"]] == [
        ("C", "7:30", "COOKING"),
        ("D", "9:01", "PHILOSOPHY"),
        ("L1", "10:33", "Homeroom B"),
        ("L2", "11:02", "LUNCH/BREAK 2"),
        ("G", "11:31", "GERMAN"),
        ("H", "1:02", "HEALTH"),
    ]


def test_build_day_spring_blank_block_and_untimed_early_dismissal():
    spring = build_day(date(2027, 2, 2), "open", "Day 6", ["C", "D", "G", "H"], EAST, LIST, "S2")
    assert [b["course_name"] for b in spring["blocks"] if b["name"] in "CDH"] == [None, "PHYS ED", None]
    early = build_day(date(2026, 12, 4), "early_dismissal", "Day 6", ["C", "D", "G", "H"], EAST, LIST, "S1")
    assert not early["timed"]
    assert [(b["name"], b["start_label"]) for b in early["blocks"]] == [("C", None), ("D", None), ("G", None), ("H", None)]
