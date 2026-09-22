"""Elementary specials (Art, PE, Music, …) by rotation day, per student."""

import re
from datetime import date

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem, StudentSpecial

_DAY_RE = re.compile(r"^\s*Day\s+(\d+)\s*$", re.I)


def rotation_number(title: str | None) -> int | None:
    m = _DAY_RE.match(title or "")
    return int(m.group(1)) if m else None


async def rotation_day_numbers(db: AsyncSession, school: School) -> list[int]:
    """The rotation days this school's calendar actually uses (1-5 for
    Cherry Hill elementary), from the "Day N" items that apply to it."""
    scope = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope = or_(scope, SchoolContentItem.district_id == school.district_id)
    rows = (
        await db.execute(
            select(SchoolContentItem.title, SchoolContentItem.applies_to_school_types)
            .where(scope, SchoolContentItem.is_current.is_(True), SchoolContentItem.title.op("~*")(r"^\s*Day\s+[0-9]+\s*$"))
        )
    ).all()
    numbers = {
        n
        for title, types in rows
        if (n := rotation_number(title)) and n > 0 and (not types or not school.school_type or school.school_type in types)
    }
    return sorted(numbers)


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
