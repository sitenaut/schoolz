"""Names for auto-created scan jobs.

`scheduled_jobs` is unique on (owner, kind, name), and a school's name is not
unique: Stratford and Westville each have a "Parkview Elementary School", and
across states it gets common (every state has a Lincoln Elementary). A job
finds its school through `params["school_id"]` and the school's own
`*_job_id` pointer, never through its name, so the name is a label - but it
still has to be distinct, and an admin looking at the Jobs list needs to tell
the two apart. So a school-level job carries its district."""

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, School


async def school_job_name(db: AsyncSession, label: str, school: School) -> str:
    """`"Staff roster scan: Parkview Elementary School (Stratford School District)"`.
    A school with no district keeps the bare form."""
    district_name = None
    if school.district_id:
        district_name = (await db.execute(select(District.name).where(District.id == school.district_id))).scalar_one_or_none()
    return f"{label}: {school.name} ({district_name})" if district_name else f"{label}: {school.name}"
