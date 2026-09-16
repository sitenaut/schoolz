from services.school_status import is_status_title, same_status_fact, status_kind, status_subject


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


# The district ics feed and a school's own newsletter word the same closure
# differently, which produced real duplicate calendar rows for both Yom
# Kippur and Labor Day - the feed says "SCHOOLS CLOSED - X" as an "event",
# the newsletter says "No School - X" as a "reminder".


def test_the_same_closure_worded_two_ways_is_one_fact():
    assert same_status_fact("No School - Yom Kippur", "SCHOOLS CLOSED - Yom Kippur")
    assert same_status_fact("No School - Labor Day", "SCHOOLS CLOSED - Labor Day")


def test_in_service_phrasings_match():
    assert same_status_fact("IN-SERVICE", "In-Service Days")


def test_a_bare_closure_has_an_empty_but_real_subject():
    assert status_subject("SCHOOLS CLOSED") == ""
    assert same_status_fact("SCHOOLS CLOSED", "DISTRICT CLOSED")


def test_unrelated_facts_sharing_a_date_are_never_merged():
    # Every one of these really does collide on a date in prod. Matching on
    # date alone would have overwritten the left-hand row with the right.
    for a, b in [
        ("Cell Phone Policy - Personal Internet Enabled Devices Prohibited", "IN-SERVICE"),
        ("In-Service Days", "Board of Education meeting"),
        ("NJ Week of Respect", "Curriculum & Instruction Committee Meeting"),
        ("Flu Vaccination Requirement", "STUDENT EARLY DISMISSAL (PRESCHOOL-8): Pre-K Conferences"),
    ]:
        assert not same_status_fact(a, b), f"{a!r} should not match {b!r}"


def test_a_closure_and_a_half_day_sharing_a_subject_are_different_facts():
    assert not same_status_fact("SCHOOLS CLOSED - Thanksgiving", "EARLY DISMISSAL - Thanksgiving")


def test_an_early_dismissal_for_in_service_identifies_as_early_not_closed():
    # It matches CLOSED_RE too, via "in-service". classify_day deliberately
    # calls this day closed; for *identity* it must stay an early dismissal,
    # or it could be merged with a real closure on the same date.
    assert status_kind("EARLY DISMISSAL - Staff In-Service") == "early"


def test_a_non_status_title_has_no_subject():
    assert status_subject("Back to School Night") is None
    assert status_kind("Board of Education Meeting") is None
