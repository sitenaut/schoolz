from datetime import date

import pytest

from services import menu_filenames

TODAY = date(2026, 10, 29)


@pytest.mark.parametrize(
    "url,meal,label,bands",
    [
        # Mantua: a month, a filler word, the meal; the breakfast file leads with the year.
        ("https://x/ourpages/auto/2026/10/1/41866544/october%20rough%20lunch.pdf?rnd=1791389795291", "lunch", "October 2026", None),
        ("https://x/ourpages/auto/2026/10/1/41866544/2026_Oct_Breakfast_2.pdf?rnd=1791319145571", "breakfast", "October 2026", None),
        # Elk (Drive titles) and Township of Franklin: Nutri-Serve's own naming.
        ("https://drive.google.com/K-6%20Aura%20LunchMenu_2026-10-OCT.pptx.png", "lunch", "October 2026", ("elementary",)),
        ("https://drive.google.com/PREK-V-LunchMenu_2026-10-OCT.pptx.png", "lunch", "October 2026", ("other",)),
        ("https://files-backend.assets.thrillshare.com/d/FTS-LunchMenu_2026-10-OCT.pdf?disposition=inline", "lunch", "October 2026", None),
        # Swedesboro-Woolwich: the band glued to the meal, a 2- or 4-digit year after the month.
        ("https://resources.finalsite.net/images/v1/x/SWE-ELEMLUNCHMENU-OCT26.pdf", "lunch", "October 2026", ("elementary",)),
        ("https://resources.finalsite.net/images/v1/x/SWE-HILLLUNCHMENU-NOV2026.pdf", "lunch", "November 2026", None),
        ("https://resources.finalsite.net/images/v1/x/SWE-ALLBREAKFASTMENU-NOV2026.pdf", "breakfast", "November 2026", None),
        # Deptford: MS and HS share one "Secondary" menu.
        ("https://deptfordschools.org/Lunch%20Menus/26-27/Elementary%20Menu%20October%202026.pdf", "lunch", "October 2026", ("elementary",)),
        ("https://deptfordschools.org/Lunch%20Menus/26-27/Secondary%20Menu%20October%202026.pdf", "lunch", "October 2026", ("middle", "high")),
        # Harrison Township: the year first, nothing else.
        ("https://x/2026October.pdf", "lunch", "October 2026", None),
        ("https://x/MS-HS_Lunch_Menu_Dec_2026.pdf", "lunch", "December 2026", ("middle", "high")),
    ],
)
def test_classify_reads_a_menu_name_wherever_its_parts_sit(url, meal, label, bands):
    got = menu_filenames.classify(url, TODAY)
    assert (got["meal_type"], got["period_label"], got["bands"]) == (meal, label, bands)


def test_a_name_without_a_year_takes_the_nearest_one():
    assert menu_filenames.classify("https://x/january%20lunch.pdf", TODAY)["period_label"] == "January 2027"
    assert menu_filenames.classify("https://x/october%20rough%20lunch.pdf", TODAY)["period_label"] == "October 2026"


@pytest.mark.parametrize(
    "url",
    [
        "https://x/Static%20Breakfast%20Menu%20(2).pptx.pdf",  # no month
        "https://x/8500%20Food%20Services%20(M).pdf",
        "https://x/Certified%20Minutes%2025%2026%20Nutri%20Serve.pdf",
        "https://x/Welcome%20Back%20Letter%2026_27%20English.pdf",
        "https://x/October_2026_lunch_spreadsheet.pdf",
        "https://x/Summer%20Lunch%20Information.pdf",
        "https://x/October-2026-Board-Agenda.pdf",  # a month, but nothing menu-like
        "https://x/summary-may-be.pdf",
        "https://x/Janvier%20Breakfast%20After%20the%20Bell%20Parent%20Letter.pdf",
    ],
)
def test_a_name_that_is_not_a_monthly_menu_is_refused(url):
    assert menu_filenames.classify(url, TODAY) is None


SCHOOLS = [
    {"id": "s1", "name": "Margaret Clifford School", "short_name": "Clifford", "school_type": "elementary"},
    {"id": "s2", "name": "Charles Stratton School", "short_name": "Stratton", "school_type": "elementary"},
    {"id": "s3", "name": "Walter Hill School", "short_name": "Hill", "school_type": "elementary"},
]


def test_named_school_finds_the_one_a_file_is_for():
    assert menu_filenames.named_school("swe-hilllunchmenu-nov2026", SCHOOLS)["id"] == "s3"
    assert menu_filenames.named_school("swe-elemlunchmenu-nov2026", SCHOOLS) is None
    # Two schools named: nobody's own.
    assert menu_filenames.named_school("clifford-and-stratton-lunch", SCHOOLS) is None


def test_a_word_two_schools_share_names_neither():
    two = [
        {"id": "a", "name": "Franklin Main Street School", "short_name": "Main Street", "school_type": "elementary"},
        {"id": "b", "name": "Franklin Janvier School", "short_name": "Janvier", "school_type": "elementary"},
    ]
    assert menu_filenames.named_school("franklin-lunch-menu", two) is None
    assert menu_filenames.named_school("fts-janvier-breakfastmenu", two)["id"] == "b"
