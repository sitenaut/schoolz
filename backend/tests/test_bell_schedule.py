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
