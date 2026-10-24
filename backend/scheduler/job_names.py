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

from models import District, ScheduledJob, School, SmoreNewsletter

HOME_STATE = "NJ"


def district_label(name: str, state: str | None) -> str:
    """"Woodbury City Public School District" for a New Jersey district,
    "Lincoln School District (PA)" for any other state's."""
    return name if not state or state == HOME_STATE else f"{name} ({state})"


def district_job_name(label: str, district: District) -> str:
    return f"{label}: {district_label(district.name, district.state)}"


async def _school_label(db: AsyncSession, school: School) -> str:
    district_name = None
    if school.district_id:
        row = (await db.execute(select(District.name, District.state).where(District.id == school.district_id))).one_or_none()
        district_name = district_label(row.name, row.state) if row else None
    return f"{school.name} ({district_name})" if district_name else school.name


async def school_job_name(db: AsyncSession, label: str, school: School) -> str:
    """`"Staff roster scan: Parkview Elementary School (Stratford School District)"`.
    A school with no district keeps the bare form."""
    return f"{label}: {await _school_label(db, school)}"


async def newsletter_job_name(db: AsyncSession, label: str, newsletter: SmoreNewsletter, owner_user_id: str | None, kind: str) -> str:
    """`"Smore scan: PTA Newsletter - Parkview Elementary School (Stratford School District)"`.

    Newsletter labels repeat from school to school (most have a "PTA
    Newsletter"), and the bare `"Smore scan: PTA Newsletter"` 500'd the
    second one, or failed a whole import. So a labelled newsletter's job also
    names its school or district. An unlabelled one is named by its URL,
    which no other newsletter has, and so is a label that still clashes (two
    "PTA Newsletter"s at one school). Jobs made before this keep their names:
    nothing finds a newsletter's job by name (`SmoreNewsletter.scheduled_job_id`)."""
    by_url = f"{label}: {newsletter.url}"[:200]
    if not newsletter.label:
        return by_url
    where = None
    if newsletter.school_id and (school := await db.get(School, newsletter.school_id)):
        where = await _school_label(db, school)
    elif newsletter.district_id and (district := await db.get(District, newsletter.district_id)):
        where = district_label(district.name, district.state)
    name = (f"{label}: {newsletter.label} - {where}" if where else f"{label}: {newsletter.label}")[:200]
    taken = (
        await db.execute(
            select(ScheduledJob.id).where(ScheduledJob.owner_user_id == owner_user_id, ScheduledJob.kind == kind, ScheduledJob.name == name)
        )
    ).first()
    return by_url if taken else name
