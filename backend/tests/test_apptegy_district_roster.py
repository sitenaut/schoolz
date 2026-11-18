import pytest

import database
from models import District, School
from scheduler.jobs.staff_roster_scan import apptegy_school_departments


def test_alias_chip_matches_the_school():
    school = School(name="Indian Mills Memorial School", website_url="https://www.shamongschools.org/o/imms", school_type="middle")
    assert apptegy_school_departments(school, same_type_siblings=0) == {"IMMS", "MS", "INDIAN MILLS MEMORIAL SCHOOL", "INDIAN MILLS MEMORIAL"}


def test_type_chip_only_when_the_school_is_alone_in_its_type():
    school = School(name="Simmons Elementary", website_url="https://www.claytonps.org/o/ses", school_type="elementary")
    assert apptegy_school_departments(school, same_type_siblings=0) == {"SES", "ES", "SIMMONS ELEMENTARY", "SIMMONS"}
    assert apptegy_school_departments(school, same_type_siblings=1) == {"SES", "SIMMONS ELEMENTARY", "SIMMONS"}


def test_a_chip_named_for_the_building():
    # Township of Franklin's district org: "Mary F. Janvier School".
    school = School(name="Mary F. Janvier School", website_url="https://janvier.franklintwpschools.org/o/mfjs", school_type="elementary")
    assert "MARY F. JANVIER SCHOOL" in apptegy_school_departments(school, same_type_siblings=2)


def test_a_chip_without_the_type_word():
    # Kearny: "Lincoln", "Kearny High", "Garfield".
    middle = School(name="Lincoln Middle School", short_name="Lincoln Middle", website_url="https://www.kearnyschools.com/o/lms", school_type="middle")
    high = School(name="Kearny High School", short_name="Kearny High", website_url="https://www.kearnyschools.com/o/khs", school_type="high")
    assert "LINCOLN" in apptegy_school_departments(middle, same_type_siblings=0)
    assert "KEARNY HIGH" in apptegy_school_departments(high, same_type_siblings=0)


@pytest.mark.anyio
async def test_a_school_org_returning_the_whole_district_is_narrowed_to_its_building(monkeypatch):
    from scheduler.jobs import staff_roster_scan

    async with database.SessionLocal() as db:
        district = District(name="Kearny Test District")
        db.add(district)
        await db.flush()
        garfield = School(name="Garfield Elementary School", short_name="Garfield", slug="t-kearny-garfield", school_type="elementary", district_id=district.id)
        lincoln = School(name="Lincoln Middle School", short_name="Lincoln Middle", slug="t-kearny-lincoln", school_type="middle", district_id=district.id)
        db.add_all([garfield, lincoln])
        await db.flush()
        roster = [
            {"department": "Garfield", "full_name": "A"},
            {"department": "Lincoln", "full_name": "B"},
            {"department": "Central Office", "full_name": "C"},
        ]
        kept, checked = await staff_roster_scan._narrow_to_building(db, garfield, roster, "Apptegy org 1")
        assert [p["full_name"] for p in kept] == ["A"] and "narrowed" in checked

        own = [{"department": "Math", "full_name": "D"}, {"department": "Garfield", "full_name": "E"}]
        kept, _ = await staff_roster_scan._narrow_to_building(db, garfield, own, "Apptegy org 1")
        assert len(kept) == 2
