"""Elementary specials (Art, PE, Music, …) by rotation day, per student."""

from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem, StudentSpecial
from services import rotation_day


def rotation_number(title: str | None) -> int | None:
    """The number a day's specials are stored under: 3 for "Day 3", for
    "Day C" and for "Day 3 (Half Day)". None for anything else."""
    rd = rotation_day.parse(title)
    return rd.number if rd else None


async def rotation_days(db: AsyncSession, school: School) -> tuple[list[int], bool]:
    """The rotation days this school's calendar actually uses (1-5 for
    Cherry Hill elementary, 1-6 for Mantua's A-F), from the "Day N" / "Day C"
    items that apply to it, and whether it names them by letter."""
    scope = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope = or_(scope, SchoolContentItem.district_id == school.district_id)
    rows = (
        await db.execute(
            select(SchoolContentItem.title, SchoolContentItem.applies_to_school_types)
            .where(scope, SchoolContentItem.is_current.is_(True), SchoolContentItem.title.op("~*")(r"^\s*(day\s+[0-9a-l]+|[a-l]\s+day)\s*(\([^)]*\))?\s*$"))
        )
    ).all()
    numbers: set[int] = set()
    lettered = numbered = 0
    for title, types in rows:
        if (n := rotation_number(title)) and n > 0 and (not types or not school.school_type or school.school_type in types):
            numbers.add(n)
            if rotation_day.parse(title).lettered:
                lettered += 1
            else:
                numbered += 1
    return sorted(numbers), lettered > numbered


async def specials_by_student(db: AsyncSession, student_ids: list[str]) -> dict[str, dict[int, str]]:
    if not student_ids:
        return {}
    rows = (await db.execute(select(StudentSpecial).where(StudentSpecial.student_id.in_(student_ids)))).scalars().all()
    out: dict[str, dict[int, str]] = {}
    for r in rows:
        out.setdefault(r.student_id, {})[r.rotation_day] = r.subject
    return out


def subject_on(specials: dict[int, str], rotation_title: str | None) -> str | None:
    n = rotation_number(rotation_title)
    return specials.get(n) if n else None


def by_date(specials: dict[int, str], rotations: dict[date, str | None]) -> dict[str, str]:
    return {d.isoformat(): s for d, t in rotations.items() if (s := subject_on(specials, t))}
