from services.schoolcafe import day_description, match_school


def _cafe(*names: str) -> list[dict]:
    return [{"SchoolId": f"id-{i}", "SchoolName": n} for i, n in enumerate(names)]


def test_exact_match_ignoring_punctuation_and_case():
    school = match_school("Edward T. Hamilton Elementary", _cafe("Edward T Hamilton Elementary School"))
    assert school["SchoolId"] == "id-0"


def test_matches_when_theirs_has_an_extra_word_we_dont():
    """Zane Elementary" (ours) vs their "Zane North Elementary School"."""
    school = match_school("Zane Elementary", _cafe("Zane North Elementary School"))
    assert school["SchoolId"] == "id-0"


def test_matches_when_ours_has_an_extra_word_theirs_doesnt():
    """Regression: Collingswood's "William P. Tatem Elementary" (our
    middle initial) against SchoolCafé's "William Tatem Elementary School"
    (no middle initial) - every other token lines up, but the old
    one-directional containment check required ours to be a subset of
    theirs, so the extra "P" token failed the match outright."""
    school = match_school("William P. Tatem Elementary", _cafe("William Tatem Elementary School"))
    assert school["SchoolId"] == "id-0"


def test_no_match_when_ambiguous():
    school = match_school("Elementary", _cafe("North Elementary School", "South Elementary School"))
    assert school is None


def test_high_and_middle_are_not_stripped_as_noise_words():
    """Regression: Collingswood's high and middle schools are literally
    named "Collingswood High School" / "Collingswood Middle School" - the
    old noise list stripped "high"/"middle" as if they were generic
    institution-type suffixes (fine for "Cherry Hill High School East",
    where "East" survives as the real distinguisher), which collapsed both
    to the identical token "collingswood" and made them ambiguous against
    each other - 0 matches for either, not a wrong match, but still a
    silent loss of two schools' menus."""
    cafe = _cafe("Collingswood High School", "Collingswood Middle School")
    assert match_school("Collingswood High School", cafe)["SchoolId"] == "id-0"
    assert match_school("Collingswood Middle School", cafe)["SchoolId"] == "id-1"


def test_no_match_when_genuinely_different_schools():
    school = match_school("Zane Elementary", _cafe("Kresson Elementary School"))
    assert school is None


def test_day_description_lists_entrees_only():
    categories = {
        "ENTREES": [{"MenuItemDescription": "Cheese Pizza"}, {"MenuItemDescription": "Chicken Tenders"}, {"MenuItemDescription": "Cheese Pizza"}],
        "MILK": [{"MenuItemDescription": "1% Milk"}],
    }
    assert day_description(categories) == "Cheese Pizza, Chicken Tenders"


def test_hand_typed_cafe_names_match_by_squashed_form():
    names = ["Country Side Elem School", "Mt. Laurel Hartford School", "SpringvilleElem School", "Fleetwood Elem School"]
    cafe = [{"SchoolName": n} for n in names]
    assert match_school("Countryside Elementary School", cafe)["SchoolName"] == names[0]
    assert match_school("Mount Laurel Hartford School", cafe)["SchoolName"] == names[1]
    assert match_school("Springville Elementary School", cafe)["SchoolName"] == names[2]
    assert match_school("Parkway Elementary School", cafe) is None


def test_numeric_ordinal_grade_names_match_spelled_out_ones():
    school = match_school("Haines 6th Grade Center", _cafe("Haines Sixth Grade Center"))
    assert school and school["SchoolName"] == "Haines Sixth Grade Center"


def test_upper_elementary_matches_middle_school():
    cafe = _cafe("Bell Oaks Upper Elementary School", "Bellmawr Park Elementary School")
    assert match_school("Bell Oaks Middle School", cafe)["SchoolId"] == "id-0"
