from models import School
from scheduler.jobs.staff_roster_scan import apptegy_school_departments


def test_alias_chip_matches_the_school():
    school = School(name="Indian Mills Memorial School", website_url="https://www.shamongschools.org/o/imms", school_type="middle")
    assert apptegy_school_departments(school, same_type_siblings=0) == {"IMMS", "MS", "INDIAN MILLS MEMORIAL SCHOOL", "INDIAN MILLS MEMORIAL"}


def test_type_chip_only_when_the_school_is_alone_in_its_type():
    school = School(name="Simmons Elementary", website_url="https://www.claytonps.org/o/ses", school_type="elementary")
    assert apptegy_school_departments(school, same_type_siblings=0) == {"SES", "ES", "SIMMONS ELEMENTARY"}
    assert apptegy_school_departments(school, same_type_siblings=1) == {"SES", "SIMMONS ELEMENTARY"}


def test_a_chip_named_for_the_building():
    # Township of Franklin's district org: "Mary F. Janvier School".
    school = School(name="Mary F. Janvier School", website_url="https://janvier.franklintwpschools.org/o/mfjs", school_type="elementary")
    assert "MARY F. JANVIER SCHOOL" in apptegy_school_departments(school, same_type_siblings=2)
