from services import njdoe_directory as nj

ROW = {
    "District Name": "Evesham Township School District",
    "School Name": "Robert B Jaggard School",
    "Princ. Title 2": "School Principal",
    "Princ. First Name": "Robert",
    "Princ. Last Name": "Fox",
    "Princ. Email": "Morrism@evesham.k12.nj.us",
    "HIB First Nname": "Stephanie",
    "HIB Last Name": "Rice",
    "HIB Title2": "Anti-Bullying Specialist",
}


def test_stale_email_is_dropped_but_person_kept():
    c = nj.contacts(ROW)
    assert c["njdoe:principal"]["full_name"] == "Robert Fox"
    assert c["njdoe:principal"]["email"] is None
    assert c["njdoe:hib"]["full_name"] == "Stephanie Rice"


def test_email_kept_when_it_names_the_person():
    assert nj.email_matches_person("diblasin@evesham.k12.nj.us", "DiBlasi")


def test_matches_person_named_school_and_refuses_ambiguity():
    rows = [
        ROW,
        {**ROW, "School Name": "Helen L Beeler"},
        {**ROW, "School Name": "Marlton Elementary"},
        {**ROW, "School Name": "Marlton Middle"},
    ]
    d = "Evesham Township School District"
    assert nj.match_row(rows, d, "Jaggard Elementary School")["School Name"] == "Robert B Jaggard School"
    assert nj.match_row(rows, d, "Beeler Elementary School")["School Name"] == "Helen L Beeler"
    assert nj.match_row(rows, d, "Marlton Preschool Center") is None
