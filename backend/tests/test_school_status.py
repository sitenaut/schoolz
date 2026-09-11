from services.school_status import is_status_title


def test_closure_titles_are_status_titles():
    assert is_status_title("SCHOOLS CLOSED - Labor Day")
    assert is_status_title("DISTRICT CLOSED")
    assert is_status_title("In-Service Day")


def test_half_day_titles_are_status_titles():
    assert is_status_title("First Day of School (Early Dismissal)")
    assert is_status_title("Half Day - Parent Conferences")


def test_delay_titles_are_status_titles():
    assert is_status_title("2 Hour Delay")
    assert is_status_title("Delayed Opening")


def test_ordinary_event_titles_are_not_status_titles():
    assert not is_status_title("Back to School Night")
    assert not is_status_title("Board of Education Meeting")
    assert not is_status_title("Day 3")
