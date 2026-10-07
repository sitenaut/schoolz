from services import schoolcafe

LINDENWOLD = [{"SchoolName": n} for n in ("Lindenwold High School", "Lindenwold Middle School", "Lindenwold Preschool", "Lindenwold School 4", "Lindenwold School 5")]
PINE_HILL = [{"SchoolName": n} for n in ("Dr. Albert Bean Elem School", "John Glenn Elem School", "Overbrook Senior High", "Pine Hill Middle School")]


def test_spelled_number_matches_digit():
    assert schoolcafe.match_school("Lindenwold School Five", LINDENWOLD)["SchoolName"] == "Lindenwold School 5"
    assert schoolcafe.match_school("Lindenwold School Four", LINDENWOLD)["SchoolName"] == "Lindenwold School 4"


def test_elem_and_middle_initial_match():
    assert schoolcafe.match_school("Dr. Albert M. Bean Elementary School", PINE_HILL)["SchoolName"] == "Dr. Albert Bean Elem School"
    assert schoolcafe.match_school("John H. Glenn Elementary School", PINE_HILL)["SchoolName"] == "John Glenn Elem School"


def test_numbered_schools_do_not_cross_match():
    assert schoolcafe.match_school("Lindenwold Early Childhood Center", LINDENWOLD) is None
