from datetime import datetime
from zoneinfo import ZoneInfo

from services.bell_schedule import current_period

TZ = ZoneInfo("America/New_York")

PERIODS = {
    "regular": [
        {"name": "1", "start": "07:30", "end": "08:27"},
        {"name": "5", "start": "12:32", "end": "13:29"},
        {"name": "6", "start": "13:33", "end": "14:30"},
    ],
    "early_dismissal": [{"name": "1", "start": "07:30", "end": "08:00"}],
    "delayed_opening": [{"name": "1", "start": "09:30", "end": "10:07"}],
}


def _at(h, m):
    return datetime(2026, 9, 9, h, m, tzinfo=TZ)


def test_finds_the_period_containing_now_and_computes_minutes():
    result = current_period(PERIODS, "open", _at(13, 38))
    assert result["name"] == "6"
    assert result["minutes_in"] == 5
    assert result["minutes_left"] == 52
    assert result["next_name"] is None
    assert result["start_label"] == "1:33 PM"
    assert result["end_label"] == "2:30 PM"


def test_next_name_points_at_the_following_period():
    result = current_period(PERIODS, "open", _at(13, 0))
    assert result["name"] == "5"
    assert result["next_name"] == "6"


def test_none_between_periods_before_first_or_after_last():
    assert current_period(PERIODS, "open", _at(6, 0)) is None  # before period 1
    assert current_period(PERIODS, "open", _at(15, 0)) is None  # after period 6
    assert current_period(PERIODS, "open", _at(10, 0)) is None  # a gap the table doesn't name


def test_status_selects_the_matching_variant():
    assert current_period(PERIODS, "early_dismissal", _at(7, 45))["name"] == "1"
    assert current_period(PERIODS, "delayed", _at(9, 45))["name"] == "1"
    # Same clock time, but "open"/regular's period 1 already ended by 9:45.
    assert current_period(PERIODS, "open", _at(9, 45)) is None


def test_none_for_closed_weekend_or_missing_table():
    assert current_period(PERIODS, "closed", _at(13, 0)) is None
    assert current_period(PERIODS, "weekend", _at(13, 0)) is None
    assert current_period(None, "open", _at(13, 0)) is None
    assert current_period({}, "open", _at(13, 0)) is None


def test_school_update_bell_periods_rejects_unknown_variant_key():
    import pytest
    from pydantic import ValidationError

    from schemas import SchoolUpdate

    with pytest.raises(ValidationError):
        SchoolUpdate(bell_periods={"bogus": [{"name": "1", "start": "07:30", "end": "08:00"}]})


def test_school_update_bell_periods_accepts_known_variants():
    from schemas import SchoolUpdate

    payload = SchoolUpdate(bell_periods={"regular": [{"name": "1", "start": "07:30", "end": "08:00"}]})
    assert payload.bell_periods["regular"][0].name == "1"


def test_school_update_bell_periods_rejects_bad_time_format():
    import pytest
    from pydantic import ValidationError

    from schemas import SchoolUpdate

    with pytest.raises(ValidationError):
        SchoolUpdate(bell_periods={"regular": [{"name": "1", "start": "7:30am", "end": "08:00"}]})


from services.bell_schedule import lettered_day  # noqa: E402

EAST = {
    "regular": [
        {"name": n, "start": s, "end": e}
        for n, s, e in [("1", "07:30", "08:27"), ("2", "08:31", "09:28"), ("3", "09:32", "10:29"), ("L1", "10:33", "10:58"),
                        ("L2", "11:02", "11:27"), ("4", "11:31", "12:28"), ("5", "12:32", "13:29"), ("6", "13:33", "14:30")]
    ],
    "long_block": [
        {"name": n, "start": s, "end": e}
        for n, s, e in [("1", "07:30", "08:57"), ("2", "09:01", "10:29"), ("L1", "10:33", "10:58"),
                        ("L2", "11:02", "11:27"), ("3", "11:31", "12:58"), ("4", "13:02", "14:30")]
    ],
    "early_dismissal": [
        {"name": n, "start": s, "end": e}
        for n, s, e in [("1", "07:30", "08:00"), ("2", "08:04", "08:34"), ("3", "08:38", "09:08"), ("L1", "09:12", "09:37"),
                        ("L2", "09:41", "10:06"), ("4", "10:10", "10:39"), ("5", "10:43", "11:12"), ("6", "11:16", "11:45")]
    ],
}


def test_lettered_day_zips_legend_letters_onto_slots_keeping_lunch_band():
    variant, slots = lettered_day(EAST, "open", ["D", "A", "B", "H", "E", "F"])
    assert variant == "regular"
    assert [s["name"] for s in slots] == ["D", "A", "B", "L1", "L2", "H", "E", "F"]
    assert slots[1]["start"] == "08:31"


def test_lettered_day_four_letters_pick_the_long_block_table():
    variant, slots = lettered_day(EAST, "open", ["A", "B", "E", "F"])
    assert variant == "long_block"
    assert [(s["name"], s["end"]) for s in slots][:2] == [("A", "08:57"), ("B", "10:29")]


def test_lettered_day_none_when_no_table_fits():
    # A long-block day with an early dismissal: no published timetable.
    assert lettered_day(EAST, "early_dismissal", ["C", "D", "G", "H"]) is None
    assert lettered_day({"regular": EAST["regular"]}, "open", ["A", "B", "E", "F"]) is None
    assert lettered_day(EAST, "closed", ["A", "B", "C", "E", "F", "G"]) is None
    assert lettered_day(EAST, "open", None) is None


def test_lettered_day_early_dismissal_on_a_six_block_day():
    variant, slots = lettered_day(EAST, "early_dismissal", ["A", "B", "C", "E", "F", "G"])
    assert variant == "early_dismissal"
    assert (slots[-1]["name"], slots[-1]["end"]) == ("G", "11:45")


def test_lettered_day_feeds_current_period_with_block_names():
    _, slots = lettered_day(EAST, "open", ["A", "B", "E", "F"])
    result = current_period({"regular": slots}, "open", _at(8, 40))
    assert result["name"] == "A"
    assert result["end_label"] == "8:57 AM"
    assert result["next_name"] == "B"


def test_is_long_block_day_from_the_rotation_not_the_timetable():
    from services.bell_schedule import is_long_block_day

    regular_only = {"regular": EAST["regular"]}
    assert is_long_block_day(regular_only, ["C", "D", "G", "H"]) is True
    assert is_long_block_day(regular_only, ["A", "B", "C", "E", "F", "G"]) is False
    assert is_long_block_day(regular_only, None) is False
    assert is_long_block_day(None, ["A", "B", "E", "F"]) is False


WEST_LONG_EARLY = [
    {"name": n, "start": s, "end": e}
    for n, s, e in [("1", "07:30", "08:17"), ("2", "08:21", "09:08"), ("L1", "09:12", "09:37"),
                    ("L2", "09:41", "10:06"), ("3", "10:10", "10:55"), ("4", "10:59", "11:45")]
]
WEST_LONG_DELAYED = [
    {"name": n, "start": s, "end": e}
    for n, s, e in [("1", "09:30", "10:28"), ("2", "10:32", "11:29"), ("L1", "11:33", "11:58"),
                    ("L2", "12:02", "12:27"), ("3", "12:31", "13:28"), ("4", "13:32", "14:30")]
]


def test_a_long_block_early_dismissal_uses_its_own_table():
    # The real Dec 4 case: "6 (Early Dismissal - Afternoon PD)", Day 6 = C, D, G, H.
    periods = {**EAST, "long_block_early_dismissal": WEST_LONG_EARLY}
    variant, slots = lettered_day(periods, "early_dismissal", ["C", "D", "G", "H"])
    assert variant == "long_block_early_dismissal"
    assert [(s["name"], s["start"], s["end"]) for s in slots][-2:] == [("G", "10:10", "10:55"), ("H", "10:59", "11:45")]
    # A six-block early dismissal still gets the six-slot table.
    assert lettered_day(periods, "early_dismissal", ["A", "B", "C", "E", "F", "G"])[0] == "early_dismissal"


def test_a_long_block_delayed_opening_uses_its_own_table():
    periods = {**EAST, "long_block_delayed_opening": WEST_LONG_DELAYED}
    variant, slots = lettered_day(periods, "delayed", ["A", "B", "E", "F"])
    assert variant == "long_block_delayed_opening"
    assert (slots[0]["name"], slots[0]["start"]) == ("A", "09:30")
