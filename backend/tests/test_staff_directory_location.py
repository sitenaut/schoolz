import uuid

import pytest
from sqlalchemy import select

import database
from models import School, StaffMember
from scheduler.jobs import staff_roster_scan
from services.staff_roster import directory_total, own_location_option

_DIRECTORY = """
<form><select name="const_search_location">
  <option value="">All Locations</option>
  <option value="62"> Cherokee High School </option>
  <option value="74"> District </option>
  <option value="54"> Lenape High School </option>
  <option value="70"> Sequoia Alternative Program </option>
</select></form>
"""


def test_picks_the_schools_own_location():
    assert own_location_option(_DIRECTORY, ["Lenape", "Lenape High School"]) == ("54", "Lenape High School")
    assert own_location_option(_DIRECTORY, [None, "Sequoia Alternative Program"]) == ("70", "Sequoia Alternative Program")


def test_no_location_when_none_or_several_fit():
    assert own_location_option(_DIRECTORY, ["Medford Memorial", "Medford Memorial Middle School"]) is None
    assert own_location_option("<div class='fsConstituentItem'></div>", ["Lenape High School"]) is None


def test_directory_total_reads_the_pagination_label():
    assert directory_total(['<span class="fsPaginationLabel">showing 1 - 20 of 241 constituents</span>']) == 241
    # Unknown is never taken as a full read.
    assert directory_total(["<div></div>"]) > 10_000
    assert directory_total([]) > 10_000


def _person(cid: str, title: str, location: str | None = None) -> dict:
    entry = {"constituent_id": cid, "full_name": f"Person {cid}", "title": title, "department": None, "email": f"p{cid}@example.org", "phone": None}
    if location:
        entry["location_filter"] = location
    return entry


@pytest.mark.anyio
async def test_a_narrowed_directory_drops_the_district_staff_it_no_longer_lists(monkeypatch):
    rosters = [
        [_person("1", "Principal"), _person("2", "Principal"), _person("3", "Teacher")],
        [_person("1", "Principal", "Lenape High School"), _person("3", "Teacher", "Lenape High School")],
    ]

    async def fake_fetch_roster(url, school_names=None):
        return rosters.pop(0)

    async def no_role_pages(url):
        return []

    monkeypatch.setattr(staff_roster_scan, "fetch_roster", fake_fetch_roster)
    monkeypatch.setattr(staff_roster_scan, "fetch_role_staff_scraped", no_role_pages)

    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Lenape High School {tag}", slug=f"lenape-{tag}", school_type="high", website_url=f"https://lenape-{tag}.example.org")
        db.add(school)
        await db.flush()
        db.add(StaffMember(school_id=school.id, source_constituent_id="njdoe:hib", full_name="HIB contact", title="Anti-Bullying Specialist"))
        await db.flush()

        await staff_roster_scan.run(db, {"school_id": school.id})
        await db.flush()
        await staff_roster_scan.run(db, {"school_id": school.id})
        await db.flush()

        ids = set((await db.execute(select(StaffMember.source_constituent_id).where(StaffMember.school_id == school.id))).scalars().all())
        # The other school's principal is gone; a row from another source stays.
        assert ids == {"1", "3", "njdoe:hib"}
