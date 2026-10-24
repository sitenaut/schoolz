"""Pure rules behind the Kids view (services/kids_view.py)."""
from datetime import datetime, timedelta
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
    _block("F", "12:32 PM", "1:29 PM", "CHEMISTRY 1A", teacher="Quinn, Daniel", room="C313"),
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


def test_classes_genesis_doesnt_list():
    names = {"Class of 2029", "Cougars' Book Club", "ENG 2A Block B (26-27) 121-1", "F: CHEM-1A 331-10"}
    # English matches a captured Genesis course, so the codeless classes
    # (class council, a club) aren't schoolwork. Chemistry's Genesis page
    # isn't captured yet, but its code says it's a course: it still counts.
    assert kv.classes_genesis_doesnt_list(names, {("121", "1")}) == {"Class of 2029", "Cougars' Book Club"}
    # No Genesis capture: no authority to ask, so nothing is excluded.
    assert kv.classes_genesis_doesnt_list(names, set()) == set()
    # Genesis captured, but no class name carries a code (a district that
    # names classes differently): the convention isn't proven, so nothing goes.
    assert kv.classes_genesis_doesnt_list({"Mrs. Smith's Algebra", "Class of 2029"}, {("101", "1")}) == set()


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
    ("Daniel Quinn", "dquinn@example.org"),
    ("Lisa Lee", "LLee@example.org"),
    ("Andrew Hart", "ahart@example.org"),
    ("Danielle Hartley", "dhartley@example.org"),
    ("Kevin Smith", "KSmith@example.org"),
    ("Jordan Smith", "JSmith@example.org"),
    ("Anthony Ortiz", "aortiz@example.org"),
    ("No Email", None),
]


def test_name_parts_real_shapes():
    assert kv.name_parts("Quinn, Daniel") == [("daniel", "quinn")]
    assert kv.name_parts("Lee/Park") == [(None, "lee"), (None, "park")]
    assert kv.name_parts("Anthony Ortiz") == [("anthony", "ortiz")]
    assert kv.name_parts("Mr. Ortiz") == [(None, "ortiz")]


def test_match_teacher_emails():
    assert kv.match_teacher_emails("Quinn, Daniel", STAFF) == ["dquinn@example.org"]
    # Co-taught: the teacher not in the directory simply doesn't resolve.
    assert kv.match_teacher_emails("Lee/Park", STAFF) == ["llee@example.org"]
    # "Hart" must not match "Hartley".
    assert kv.match_teacher_emails("Mr. Hart", STAFF) == ["ahart@example.org"]
    # Two Smiths and no first name: ambiguous, so no link at all.
    assert kv.match_teacher_emails("Smith", STAFF) == []
    assert kv.match_teacher_emails("Kevin Smith", STAFF) == ["ksmith@example.org"]
    assert kv.match_teacher_emails(None, STAFF) == []


def test_course_key_prefers_district_code():
    assert kv.course_key("F: CHEM-1A 331-10", "SLUG") == ("331", "10")
    assert kv.course_key("GEOM A Per A 2026-27 210-1", "SLUG") == ("210", "1")
    assert kv.course_key("Advanced Percussion", "SLUG") == ("slug:SLUG", "")
    assert kv.course_key(None, None) == ("name:unknown", "")


def test_course_progress_flags_low_grades_without_calculating_makeup():
    items = [
        {"course_key_tuple": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "missing", "due_date": "2026-09-08", "teacher_name": "Daniel Quinn", "teacher_emails": ["dquinn@example.org"]},
        {"course_key_tuple": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "done", "due_date": "2026-09-09"},
        {"course_key_tuple": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "due", "due_date": "2026-09-16"},
        {"course_key_tuple": ("331", "10"), "course_name": "F: CHEM-1A 331-10", "category": "no_due_date", "due_date": None},
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
    assert chem["teacher_emails"] == ["dquinn@example.org"]


def _policy(shape, **kw):
    base = dict(
        shape=shape, penalty_pct=None, penalty_per_day=None, floor_pct=None, window_days=None,
        steps=None, accepted_until=None, applies_to_types=None, extension_by_request=False,
    )
    base.update(kw)
    return SimpleNamespace(**base)


def test_late_credit_is_none_when_nothing_can_be_said():
    # No policy on file, and a policy scoped to other item types, are both
    # "unknown" - which must stay distinguishable from "known to be zero".
    assert kv.late_credit(None, "2026-09-01", "2026-09-14") is None
    homework_only = _policy("flat", penalty_pct=10, applies_to_types=["assignment"])
    assert kv.late_credit(homework_only, "2026-09-01", "2026-09-14", item_type="quiz") is None
    assert kv.late_credit(homework_only, "2026-09-01", "2026-09-14", item_type="assignment") is not None


def test_late_credit_full_before_the_due_date_under_every_shape():
    for shape in ("full_credit", "flat", "daily_decay", "window", "tiered", "not_accepted"):
        out = kv.late_credit(_policy(shape, penalty_pct=50, window_days=0), "2026-09-20", "2026-09-14")
        assert out["credit_pct"] == 100, shape
        assert out["accepted"] is True, shape
        assert out["is_late"] is False, shape


def test_late_credit_flat_and_daily_decay():
    flat = kv.late_credit(_policy("flat", penalty_pct=10), "2026-09-10", "2026-09-14")
    assert (flat["credit_pct"], flat["accepted"], flat["is_late"]) == (90, True, True)

    # 10%/day with a 50% floor: 4 days late is 60%, 8 days is floored at 50.
    decay = _policy("daily_decay", penalty_per_day=10, floor_pct=50)
    assert kv.late_credit(decay, "2026-09-10", "2026-09-14")["credit_pct"] == 60
    assert kv.late_credit(decay, "2026-09-06", "2026-09-14")["credit_pct"] == 50


def test_late_credit_window_closes_and_reports_days_left():
    week = _policy("window", window_days=7)
    inside = kv.late_credit(week, "2026-09-10", "2026-09-14")
    assert (inside["credit_pct"], inside["closes_on"], inside["days_left"]) == (100, "2026-09-17", 3)
    # The last day still counts; the day after does not.
    assert kv.late_credit(week, "2026-09-10", "2026-09-17")["accepted"] is True
    closed = kv.late_credit(week, "2026-09-10", "2026-09-18")
    assert (closed["accepted"], closed["credit_pct"]) == (False, 0)


def test_late_credit_tiered_picks_the_first_band_that_still_covers():
    steps = [{"days": 1, "credit_pct": 90}, {"days": 3, "credit_pct": 75}, {"days": 7, "credit_pct": 50}]
    tiered = _policy("tiered", steps=steps)
    assert kv.late_credit(tiered, "2026-09-13", "2026-09-14")["credit_pct"] == 90
    assert kv.late_credit(tiered, "2026-09-12", "2026-09-14")["credit_pct"] == 75
    assert kv.late_credit(tiered, "2026-09-08", "2026-09-14")["credit_pct"] == 50
    past = kv.late_credit(tiered, "2026-09-01", "2026-09-14")
    assert (past["accepted"], past["credit_pct"]) == (False, 0)


def test_late_credit_not_accepted_and_marking_period_end():
    never = kv.late_credit(_policy("not_accepted"), "2026-09-10", "2026-09-14")
    assert (never["accepted"], never["credit_pct"]) == (False, 0)

    # "Accepted until the end of the marking period" needs the MP's own end
    # date - the policy row only names the rule, never the date.
    mp = _policy("flat", penalty_pct=20, accepted_until="marking_period_end")
    still_open = kv.late_credit(mp, "2026-09-10", "2026-09-14", mp_end="2026-11-06")
    assert (still_open["credit_pct"], still_open["closes_on"]) == (80, "2026-11-06")
    after_mp = kv.late_credit(mp, "2026-09-10", "2026-11-07", mp_end="2026-11-06")
    assert after_mp["accepted"] is False


def test_late_credit_takes_the_earlier_of_window_and_accepted_until():
    # A 30-day window inside a marking period that ends sooner closes with
    # the marking period, not the window.
    policy = _policy("window", window_days=30, accepted_until="marking_period_end")
    out = kv.late_credit(policy, "2026-10-30", "2026-11-01", mp_end="2026-11-06")
    assert out["closes_on"] == "2026-11-06"


def test_late_credit_refuses_to_close_an_implausibly_late_item():
    # Classroom's captured due text has no year - resolve_due_date infers
    # one - so an off-by-one-year inference lands ~365 days late. Since a
    # closed item is removed from the dashboard entirely, that must read as
    # "unknown" (stays visible) rather than "closed" (vanishes).
    never = _policy("not_accepted")
    assert kv.late_credit(never, "2026-09-10", "2026-09-20")["accepted"] is False
    assert kv.late_credit(never, "2025-09-10", "2026-09-20") is None


def _exception(accepted_until, credit_pct=None):
    return SimpleNamespace(accepted_until=accepted_until, credit_pct=credit_pct, granted_note=None)


def test_a_teacher_exception_reopens_work_the_class_rule_had_closed():
    # The case this exists for: the policy says no late work at all, and the
    # teacher said "get it to me by the 6th" anyway.
    never = _policy("not_accepted")
    closed = kv.late_credit(never, "2026-09-10", "2026-09-20")
    assert closed["accepted"] is False

    reopened = kv.late_credit(never, "2026-09-10", "2026-09-20", exception=_exception("2026-11-06"))
    assert reopened["accepted"] is True
    assert reopened["credit_pct"] == 100  # "I'll take it" with no points stated
    assert reopened["closes_on"] == "2026-11-06"
    assert reopened["days_left"] == 47
    assert reopened["by_exception"] is True


def test_an_exception_keeps_the_class_gradient_when_no_credit_was_stated():
    # The teacher moved the deadline, not the penalty: 10%/day still applies,
    # but the policy's own cutoff no longer closes it.
    decay = _policy("daily_decay", penalty_per_day=10, floor_pct=50, accepted_until="2026-09-12")
    assert kv.late_credit(decay, "2026-09-10", "2026-09-20")["accepted"] is False
    with_ext = kv.late_credit(decay, "2026-09-10", "2026-09-14", exception=_exception("marking_period_end"), mp_end="2026-11-06")
    assert with_ext["credit_pct"] == 60  # 4 days late, still the class rule
    assert with_ext["accepted"] is True

    # A stated credit wins outright over the class gradient.
    stated = kv.late_credit(decay, "2026-09-10", "2026-09-14", exception=_exception("2026-11-06", credit_pct=100))
    assert stated["credit_pct"] == 100


def test_an_exception_expires_on_its_own_date():
    lapsed = kv.late_credit(_policy("flat", penalty_pct=10), "2026-09-10", "2026-11-07", exception=_exception("2026-11-06"))
    assert (lapsed["accepted"], lapsed["credit_pct"]) == (False, 0)


def test_until_the_marking_period_ends_with_no_period_on_file_is_unknown():
    # July: the last period is over and the next isn't captured. A June item
    # read "accepted at 80%" here, with no end in sight.
    mp = _policy("flat", penalty_pct=20, accepted_until="marking_period_end")
    assert kv.late_credit(mp, "2026-06-10", "2026-07-14") is None
    assert kv.late_credit(None, "2026-06-10", "2026-07-14", exception=_exception("marking_period_end")) is None


def test_an_exception_survives_the_marking_period_filter():
    # "Turn in last month's work by the end of this marking period" names
    # work whose due date sits in the PREVIOUS period - exactly what the
    # staleness filter would otherwise drop before anything else runs.
    assert kv.in_current_marking_period("missing", "2026-09-01", "2026-11-09") is False
    assert kv.in_current_marking_period("missing", "2026-09-01", "2026-11-09", has_exception=True) is True


def test_an_exception_ignores_the_implausibly_late_guard():
    # The guard exists because a due-date YEAR is inferred and can be wrong.
    # A person typing in a teacher's promise is not an inference, so it wins.
    assert kv.late_credit(_policy("not_accepted"), "2025-09-10", "2026-09-20") is None
    typed = kv.late_credit(_policy("not_accepted"), "2025-09-10", "2026-09-20", exception=_exception("2026-11-06"))
    assert typed["accepted"] is True


def test_genesis_grade_for_needs_the_due_day_when_a_title_repeats():
    newest, older = SimpleNamespace(weekday_date="Mon 10/12"), SimpleNamespace(weekday_date="Mon 10/5")
    assert kv.genesis_grade_for([], "2026-10-05", False) is None
    assert kv.genesis_grade_for([older], "2026-10-09", False) is older
    assert kv.genesis_grade_for([newest, older], "2026-10-05", True) is older
    assert kv.genesis_grade_for([older], "2026-10-12", True) is None
    assert kv.genesis_grade_for([older], None, True) is None


def test_a_teacher_exception_keeps_a_tiered_rules_last_band_past_its_cutoff():
    # "1 day late 90%, 3 days 75%, after that zero" - and the teacher said yes on day 14.
    tiered = _policy("tiered", steps=[{"days": 1, "credit_pct": 90}, {"days": 3, "credit_pct": 75}])
    assert kv.late_credit(tiered, "2026-10-01", "2026-10-15")["accepted"] is False
    reopened = kv.late_credit(tiered, "2026-10-01", "2026-10-15", exception=_exception("2026-11-10"))
    assert reopened["accepted"] is True and reopened["credit_pct"] == 75
    # A no-floor decay that has run out: still a yes, at what the rule leaves.
    decay = kv.late_credit(_policy("daily_decay", penalty_per_day=10), "2026-10-01", "2026-10-20", exception=_exception("2026-11-10"))
    assert decay["accepted"] is True and decay["credit_pct"] == 0
    # Only a stated 0% means no.
    assert kv.late_credit(tiered, "2026-10-01", "2026-10-15", exception=_exception("2026-11-10", credit_pct=0))["accepted"] is False


def test_an_unreadable_policy_cutoff_is_unknown_rather_than_an_error():
    assert kv.late_credit(_policy("flat", penalty_pct=10, accepted_until="11/10"), "2026-10-01", "2026-10-15") is None
    assert [kv.valid_accepted_until(v) for v in (None, "marking_period_end", "2026-11-10", "11/10", "")] == [
        True, True, True, False, True,
    ]


def test_right_now_ignores_an_older_years_row_on_todays_date():
    now = datetime(2026, 9, 14, 10, 30, tzinfo=ET)
    last_year = _block("A", "07:30", "08:20", "Algebra", date="09/14")
    last_year.updated_at = now - timedelta(days=365)
    assert kv.right_now([last_year], None, now)["stale"] is True
    last_year.updated_at = now - timedelta(hours=2)
    assert kv.right_now([last_year], None, now)["stale"] is False
