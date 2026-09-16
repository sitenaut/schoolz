"""District-wide staff directory - one searchable list across every
tracked school, rather than 27 separate `/schools/{id}/staff` pages.

Public, like every other read in this app: a school's staff listing is
already public on the school's own site and on the school page here, so
the aggregate view needs no account either.

Why the filtering happens in Python rather than SQL: see the comment on
`classify_directory_category` in services/staff_roles.py. The category is
derived from free text at query time, and at ~1900 rows district-wide
loading one scoped query and filtering in memory is cheaper than the
migration-plus-backfill treadmill a stored column would need every time
the keyword list is tuned. Facet counts are computed over the *search*
result set but before the category filter is applied, so the chips always
show what picking each one would actually give you.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import School, StaffMember
from schemas import DirectoryFacetOut, DirectoryPageOut, DirectoryStaffOut
from services.staff_roles import DIRECTORY_CATEGORIES, classify_directory_category

router = APIRouter(prefix="/directory", tags=["directory"])

_MAX_LIMIT = 200


def _matches(member: StaffMember, school: School, tokens: list[str]) -> bool:
    """AND across whitespace-separated tokens, OR across the fields - so
    "smith math" finds the math teacher named Smith, and "carusi nurse"
    finds the nurse at Carusi. Each token has to appear *somewhere*, which
    is what makes a two-word query narrow the list instead of widening it
    the way a naive OR would."""
    haystack = " ".join(
        part.lower()
        for part in (
            member.full_name,
            member.title,
            member.department,
            member.email,
            school.name,
            school.short_name,
        )
        if part
    )
    return all(token in haystack for token in tokens)


def _to_out(member: StaffMember, school: School, category: str) -> DirectoryStaffOut:
    return DirectoryStaffOut(
        id=member.id,
        full_name=member.full_name,
        title=member.title,
        role=member.role,
        department=member.department,
        email=member.email,
        phone=member.phone,
        category=category,
        school_id=school.id,
        school_slug=school.slug,
        school_name=school.name,
        school_short_name=school.short_name,
        school_type=school.school_type,
    )


@router.get("/staff", response_model=DirectoryPageOut)
async def search_directory(
    q: str | None = None,
    school_id: str | None = Query(default=None, description="School id or slug"),
    school_type: str | None = None,
    category: str | None = None,
    limit: int = Query(default=50, ge=1, le=_MAX_LIMIT),
    offset: int = Query(default=0, ge=0),
    db: AsyncSession = Depends(get_db),
) -> DirectoryPageOut:
    query = select(StaffMember, School).join(School, StaffMember.school_id == School.id)
    if school_id:
        # Same id-or-slug courtesy as routers/schools.py:resolve_school, so
        # a link built from a slug works here too.
        query = query.where((School.id == school_id) | (School.slug == school_id))
    if school_type:
        query = query.where(School.school_type == school_type)
    query = query.order_by(StaffMember.full_name)

    rows = (await db.execute(query)).all()

    tokens = [t for t in (q or "").lower().split() if t]
    matched = [(m, s) for m, s in rows if not tokens or _matches(m, s, tokens)]

    categorized = [(m, s, classify_directory_category(m.title, m.department)) for m, s in matched]

    counts: dict[str, int] = {}
    for _, _, cat in categorized:
        counts[cat] = counts.get(cat, 0) + 1
    facets = [
        DirectoryFacetOut(key=key, label=label, count=counts.get(key, 0))
        for key, label in DIRECTORY_CATEGORIES
        if counts.get(key, 0) > 0
    ]

    if category:
        categorized = [row for row in categorized if row[2] == category]

    page = categorized[offset : offset + limit]
    return DirectoryPageOut(
        total=len(categorized),
        limit=limit,
        offset=offset,
        items=[_to_out(m, s, cat) for m, s, cat in page],
        categories=facets,
    )
