"""Names for auto-created scan jobs.

`scheduled_jobs` is unique on (owner, kind, name), and a school's name is not
unique: Stratford and Westville each have a "Parkview Elementary School", and
across states it gets common (every state has a Lincoln Elementary). A job
finds its school through `params["school_id"]` and the school's own
`*_job_id` pointer, never through its name, so the name is a label - but it
still has to be distinct, and an admin looking at the Jobs list needs to tell
the two apart. So a school-level job carries its district.

District names are not unique across states either (see District), so a district
outside New Jersey - the state every existing job was named in - carries its
state: "Lincoln Elementary (Lincoln School District (PA))". New Jersey stays
bare so that existing job names do not change."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, School


HOME_STATE = "NJ"


def district_label(name: str, state: str | None) -> str:
    """"Woodbury City Public School District" for a New Jersey district,
    "Lincoln School District (PA)" for any other state's."""
    return name if not state or state == HOME_STATE else f"{name} ({state})"


def district_job_name(label: str, district: District) -> str:
    return f"{label}: {district_label(district.name, district.state)}"


async def school_job_name(db: AsyncSession, label: str, school: School) -> str:
    """`"Staff roster scan: Parkview Elementary School (Stratford School District)"`.
    A school with no district keeps the bare form."""
    district_name = None
    if school.district_id:
        row = (await db.execute(select(District.name, District.state).where(District.id == school.district_id))).one_or_none()
        district_name = district_label(row.name, row.state) if row else None
    return f"{label}: {school.name} ({district_name})" if district_name else f"{label}: {school.name}"
