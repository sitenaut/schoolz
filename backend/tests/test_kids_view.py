"""Pure rules behind the Kids view (services/kids_view.py)."""
from datetime import datetime
from types import SimpleNamespace
from zoneinfo import ZoneInfo

from services import kids_view as kv

ET = ZoneInfo("America/New_York")

# Real East bell table shape (School.bell_periods "regular" variant).
EAST_BELLS = {
    "regular": [
        {"name": "1", "start": "07:30", "end": "08:27"},
        {"name": "2", "start": "08:31", "end": "09:28"},
        {"name": "3", "start": "09:32", "end": "10:29"},
        {"name": "L1", "start": "10:33", "end": "10:58"},
        {"name": "L2", "start": "11:02", "end": "11:27"},
        {"name": "4", "start": "11:31", "end": "12:28"},
        {"name": "5", "start": "12:32", "end": "13:29"},
        {"name": "6", "start": "13:33", "end": "14:30"},
    ]
}


def _block(period, start, end, course, date="09/14", teacher=None, room=None):
    return SimpleNamespace(
        period=period, time_start=start, time_end=end, course_name=course,
        schedule_date=date, teacher=teacher, room=room, updated_at=None,
    )


DAY = [
    _block("A", "7:30 AM", "8:27 AM", "GEOMETRY A"),
    _block("C", "9:32 AM", "10:29 AM", "SCIENCE OF COOKING"),
    _block("L1", "10:33 AM", "10:58 AM", "Homeroom"),
    _block("F", "12:32 PM", "1:29 PM", "CHEMISTRY 1A", teacher="Rouen, Gregory", room="C313"),
    _block("G", "1:33 PM", "2:30 PM", "GERMAN I A"),
]


def test_parse_clock():
    assert kv.parse_clock("7:30 AM").hour == 7
    assert kv.parse_clock("12:32 PM").hour == 12
    assert kv.parse_clock("12:05 AM").hour == 0
    assert kv.parse_clock("1:29 PM").hour == 13
    assert kv.parse_clock("nonsense") is None


def test_right_now_in_a_block_maps_to_school_period_number():
    result = kv.right_now(DAY, EAST_BELLS, datetime(2026, 9, 14, 12, 40, tzinfo=ET))
    assert result["stale"] is False
    cur = result["current"]
    assert cur["period"] == "F"
    assert cur["period_number"] == "5"
    assert cur["course_name"] == "CHEMISTRY 1A"
    assert cur["minutes_in"] == 8
    assert cur["minutes_left"] == 49
    assert result["next"]["period"] == "G"


def test_right_now_between_blocks_shows_next_only():
    result = kv.right_now(DAY, EAST_BELLS, datetime(2026, 9, 14, 10, 30, tzinfo=ET))
    assert result["current"] is None
    assert result["next"]["period"] == "L1"
    assert result["school_day_over"] is False


def test_right_now_after_school():
    result = kv.right_now(DAY, EAST_BELLS, datetime(2026, 9, 14, 15, 0, tzinfo=ET))
    assert result["current"] is None
    assert result["next"] is None
    assert result["school_day_over"] is True


def test_right_now_never_presents_another_days_schedule_as_today():
    old_day = [_block("A", "7:30 AM", "8:27 AM", "GEOMETRY A", date="09/11")]
    result = kv.right_now(old_day, EAST_BELLS, datetime(2026, 9, 14, 7, 45, tzinfo=ET))
    assert result["stale"] is True
    assert result["current"] is None and result["next"] is None
    assert result["schedule_date"] == "09/11"
    assert len(result["blocks"]) == 1


def test_resolve_done_precedence():
    assert kv.resolve_done(True, None, False) == (True, "marked")
    # A person unchecking beats Classroom's own "Completed".
    assert kv.resolve_done(False, "Completed", True) == (False, None)
    assert kv.resolve_done(None, "Graded", False) == (True, "classroom")
    assert kv.resolve_done(None, None, True) == (True, "genesis")
    assert kv.resolve_done(None, "Assigned", False) == (False, None)


def test_todo_category():
    today = "2026-09-14"
    assert kv.todo_category("assignment", "2026-09-10", False, today) == "missing"
    assert kv.todo_category("assignment", "2026-09-14", False, today) == "due"
    assert kv.todo_category("assignment", "2026-09-10", True, today) == "done"
    assert kv.todo_category("assignment", None, False, today) == "no_due_date"
    assert kv.todo_category("material", "2026-09-20", False, today) == "no_due_date"


def test_previous_marking_period_work_drops_out():
    mp_start = "2026-11-11"
    assert kv.in_current_marking_period("missing", "2026-11-01", mp_start) is False
    assert kv.in_current_marking_period("done", "2026-11-12", mp_start) is True
    assert kv.in_current_marking_period("due", "2026-11-20", mp_start) is True
    assert kv.in_current_marking_period("missing", "2026-11-01", None) is True


def _item(title, category, due):
    return {"title": title, "category": category, "due_date": due}


def test_progress_and_next_action():
    items = [
        _item("Old missing", "missing", "2026-09-08"),
        _item("Newer missing", "missing", "2026-09-10"),
        _item("Due soon", "due", "2026-09-15"),
        _item("Done", "done", "2026-09-09"),
        _item("Done no date", "done", None),
    ]
    p = kv.progress(items)
    assert p == {"done": 1, "missing": 2, "due": 1, "total": 4, "percent": 25}
    assert kv.pick_next_action(items)["title"] == "Old missing"
    assert kv.pick_next_action([_item("B", "due", "2026-09-20"), _item("A", "due", "2026-09-16")])["title"] == "A"
    assert kv.pick_next_action([_item("Done", "done", "2026-09-09")]) is None


STAFF = [
    ("Gregory Rouen", "grouen@chclc.org"),
    ("Lisa Borrelli", "LBorrelli@chclc.org"),
    ("Andrew Graff", "agraff@chclc.org"),
    ("Danielle Graffeo", "dgraffeo@chclc.org"),
    ("Kenneth Smith", "KSmith@chclc.org"),
    ("Jordan Smith", "JSmith@chclc.org"),
    ("Anthony Maniscalco", "amaniscalco@chclc.org"),
    ("No Email", None),
]


def test_name_parts_real_shapes():
    assert kv.name_parts("Rouen, Gregory") == [("gregory", "rouen")]
    assert kv.name_parts("Borrelli/Squazzo") == [(None, "borrelli"), (None, "squazzo")]
    assert kv.name_parts("Anthony Maniscalco") == [("anthony", "maniscalco")]
    assert kv.name_parts("Mr. Maniscalco") == [(None, "maniscalco")]


def test_match_teacher_emails():
    assert kv.match_teacher_emails("Rouen, Gregory", STAFF) == ["grouen@chclc.org"]
    # Co-taught: the teacher not in the directory simply doesn't resolve.
    assert kv.match_teacher_emails("Borrelli/Squazzo", STAFF) == ["lborrelli@chclc.org"]
    # "Graff" must not match "Graffeo".
    assert kv.match_teacher_emails("Mr. Graff", STAFF) == ["agraff@chclc.org"]
    # Two Smiths and no first name: ambiguous, so no link at all.
    assert kv.match_teacher_emails("Smith", STAFF) == []
    assert kv.match_teacher_emails("Kenneth Smith", STAFF) == ["ksmith@chclc.org"]
    assert kv.match_teacher_emails(None, STAFF) == []


def test_course_key_prefers_district_code():
    assert kv.course_key("F: CHEM-1A 331-10", "SLUG") == ("331", "10")
    assert kv.course_key("GEOM A Per A 2026-27 210-1", "SLUG") == ("210", "1")
    assert kv.course_key("Advanced Percussion", "SLUG") == ("slug:SLUG", "")
    assert kv.course_key(None, None) == ("name:unknown", "")


def test_course_progress_flags_low_grades_without_calculating_makeup():
    items = [
        {"course_key": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "missing", "due_date": "2026-09-08", "teacher_name": "Gregory Rouen", "teacher_emails": ["grouen@chclc.org"]},
        {"course_key": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "done", "due_date": "2026-09-09"},
        {"course_key": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "due", "due_date": "2026-09-16"},
        {"course_key": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "no_due_date", "due_date": None},
    ]
    entries = [
        SimpleNamespace(course_code="331", course_section="10", course_name=None, title="Density Activity", percent=0.0),
        SimpleNamespace(course_code="331", course_section="10", course_name=None, title="Welcome", percent=100.0),
    ]
    grades = [SimpleNamespace(course_code="331", course_section="10", course_name=None, grade_percent=27.27, marking_period="MP1")]
    [chem] = kv.course_progress(items, entries, grades, "2026-09-14")
    assert chem["course_name"] == "F: CHEM-1A 331-10"
    assert (chem["total"], chem["done"], chem["missing"], chem["due_soon"]) == (3, 1, 1, 1)
    assert chem["completion_pct"] == 33
    assert chem["grade_percent"] == 27.27
    assert chem["low_grade_entries"] == [{"title": "Density Activity", "percent": 0.0}]
    assert chem["teacher_emails"] == ["grouen@chclc.org"]
