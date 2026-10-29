from types import SimpleNamespace

from services.schoolcafe import match_by_site_type

SITES = [
    {"SchoolId": "h", "SchoolName": "NBC Regional High School", "SiteTypeDescription": "High"},
    {"SchoolId": "m", "SchoolName": "NBC Regional Middle School", "SiteTypeDescription": "Middle"},
]


def test_the_one_site_of_the_schools_type_when_no_name_matches():
    # Northern Burlington: SchoolCafé abbreviates the district to "NBC".
    hs = SimpleNamespace(school_type="high")
    ms = SimpleNamespace(school_type="middle")
    assert match_by_site_type(hs, [hs, ms], SITES)["SchoolId"] == "h"
    assert match_by_site_type(ms, [hs, ms], SITES)["SchoolId"] == "m"


def test_no_guess_when_the_district_has_two_schools_of_that_type():
    a, b = SimpleNamespace(school_type="high"), SimpleNamespace(school_type="high")
    assert match_by_site_type(a, [a, b], SITES) is None
    assert match_by_site_type(SimpleNamespace(school_type="elementary"), [], SITES) is None
