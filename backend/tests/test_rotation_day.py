import pytest

from services import i18n_strings, rotation_day


@pytest.mark.parametrize(
    "title,key,number,lettered",
    [
        ("Day 3", "3", 3, False),
        ("day 12", "12", 12, False),
        ("Day 3 ( 3, 4, 1, LL, 7, 8, 5)", "3", 3, False),
        ("Day C", "C", 3, True),
        ("DAY F", "F", 6, True),  # Mantua
        ("A Day", "A", 1, True),  # Swedesboro-Woolwich
        ("B  Day", "B", 2, True),  # ... with its doubled space
        ("  Day D  ", "D", 4, True),
        ("DAY E (Snow Day)", "E", 5, True),
        ("Day F (makeup snow day)", "F", 6, True),
    ],
)
def test_parse_reads_numbered_and_lettered_days(title, key, number, lettered):
    rd = rotation_day.parse(title)
    assert (rd.key, rd.number, rd.lettered) == (key, number, lettered)


@pytest.mark.parametrize(
    "title",
    [
        "A Day with Dad",
        "First Day of School",
        "Day Off",
        "Day 3 Field Trip",
        "Day Camp",
        "a day",  # a lowercase letter is a word, not a rotation day
        "Day c",
        "Day M",  # past the 12 a specials table holds
        "Cycle 1 Clubs End",
        "",
        None,
    ],
)
def test_parse_refuses_everything_else(title):
    assert rotation_day.parse(title) is None


def test_canonical_title_gives_lettered_days_one_spelling_and_leaves_numbers_alone():
    assert [rotation_day.canonical_title(t) for t in ("DAY A", "A Day", "A  Day", "Day A", "DAY E (Snow Day)")] == [
        "Day A",
        "Day A",
        "Day A",
        "Day A",
        "Day E (Snow Day)",
    ]
    assert rotation_day.canonical_title("Day 3 ( 3, 4, 1)") == "Day 3 ( 3, 4, 1)"
    assert rotation_day.canonical_title("DAY 3") == "DAY 3"
    assert rotation_day.canonical_title("Board Meeting") == "Board Meeting"


def test_key_for_names_a_number_by_the_schools_convention():
    assert (rotation_day.key_for(3, lettered=True), rotation_day.key_for(3, lettered=False)) == ("C", "3")


def test_lettered_days_localize_like_numbered_ones():
    assert i18n_strings.rotation_title("DAY C", "es") == "Día C"
    assert i18n_strings.rotation_title("C Day", "zh") == "第C天"
    assert i18n_strings.rotation_title("Day E (Snow Day)", "ko") == "E일차 (Snow Day)"
    assert i18n_strings.rotation_title("Day C", "en") is None
