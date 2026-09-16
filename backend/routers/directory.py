"""District-wide staff directory - one searchable list across every
tracked school, rather than 27 separate `/schools/{id}/staff` pages.

Public, like every other read in this app: a school's staff listing is
already public on the school's own site and on the school page here, so
the aggregate view needs no account either.

**One row per person, not per school.** The same human is stored once per
school they appear at - `preschool_team.scan` deliberately writes the
district's central preschool staff to every preschool location, and the
district republishes its own administrators on each school's Finalsite
contact page. That's correct per-school data (the preschool nurse really
is *that* preschool's nurse, and `/schools/{id}/staff` still lists her),
but in an aggregate list it reads as the same person ten times. So rows
are collapsed by identity here and the person's real affiliation is shown
instead.

Identity is the **email address**, not `source_constituent_id`: the
constituent id is only unique per school (`uq_staff_member_school_constituent`),
so two unrelated people at different schools could share one, while an
email is globally unique. Verified against the live data - no address maps
to more than one name, and every multi-school person shares one address
across all their rows. The handful of rows with no email can't be matched
to anything, so each stays its own person.

Why the filtering happens in Python rather than SQL: the category is
derived from free text (see `classify_directory_category`), and the
grouping above has to happen *before* filtering anyway - filtering by
school in SQL would truncate a person's school list to the one school
that matched, so "District-wide" would silently become "Bret Harte". At
~1900 rows one scoped query plus in-memory work is cheap. Revisit if this
grows past ~10k.
"""

from fastapi import APIRouter, Depends, Query
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from models import School, StaffMember
from schemas import DirectoryFacetOut, DirectoryPageOut, DirectorySchoolOut, DirectoryStaffOut
from services.staff_roles import DIRECTORY_CATEGORIES, classify_directory_category

router = APIRouter(prefix="/directory", tags=["directory"])

_MAX_LIMIT = 200

# A person counts as district-wide when they cover *every* school of a
# single type. Deliberately not a "more than N schools" threshold: the real
# school counts run 2, 3, 4, 5, 9, 10, 11, 13, 16, 17 with no gap anywhere,
# so any cutoff would relabel a genuinely itinerant teacher ("ESL Teacher
# (East/West)", 3 schools) as district staff and throw away the school list
# that is the useful part. A type needs at least two schools for this to
# mean anything - covering the single alternative school is not "district-wide".
_DISTRICT_WIDE_MIN_SCHOOLS_IN_TYPE = 2

# Plural, parent-facing names for the school types, for the affiliation
# label ("District-wide · 10 preschools"). "other" is every private
# preschool/daycare provider - see the note in frontend/src/lib/schoolType.ts
# for why the literal word "other" never reaches a reader.
_TYPE_PLURALS = {
    "elementary": "elementary schools",
    "middle": "middle schools",
    "high": "high schools",
    "alternative": "programs",
    "other": "preschools",
}


def _identity(member: StaffMember) -> str:
    """Globally-unique key for one human. Falls back to the row's own id so
    a row with no email is never merged with another one."""
    return member.email.strip().lower() if member.email else f"row:{member.id}"


def _first(*values: str | None) -> str | None:
    """First non-empty value. A person's rows disagree in real data - the
    district's copy of someone often has no title while their own school's
    listing does - so each field takes the first row that actually has it
    rather than whichever row happened to sort first."""
    return next((v for v in values if v), None)


def _affiliation(schools: list[School], type_totals: dict[str | None, int]) -> tuple[str, bool]:
    """Human label for where this person works, plus whether it's district-wide."""
    types = {s.school_type for s in schools}
    if len(types) == 1:
        school_type = next(iter(types))
        total = type_totals.get(school_type, 0)
        if school_type and total >= _DISTRICT_WIDE_MIN_SCHOOLS_IN_TYPE and len(schools) >= total:
            plural = _TYPE_PLURALS.get(school_type, "schools")
            return f"District-wide · {total} {plural}", True

    names = sorted((s.short_name or s.name) for s in schools)
    if len(names) == 1:
        return names[0], False
    return f"{names[0]} +{len(names) - 1}", False


def _matches(person: dict, tokens: list[str]) -> bool:
    """AND across whitespace-separated tokens, OR across the fields - so
    "smith math" finds the math teacher named Smith, and "carusi nurse"
    finds the nurse at Carusi. Each token has to appear *somewhere*, which
    is what makes a two-word query narrow the list instead of widening it
    the way a naive OR would. A token can match any of the person's
    schools, not just one."""
    return all(token in person["haystack"] for token in tokens)


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
    rows = (
        await db.execute(
            select(StaffMember, School).join(School, StaffMember.school_id == School.id).order_by(StaffMember.full_name)
        )
    ).all()

    type_totals = {
        school_type_value: count
        for school_type_value, count in (await db.execute(select(School.school_type, func.count()).group_by(School.school_type))).all()
    }

    people: dict[str, dict] = {}
    for member, school in rows:
        person = people.setdefault(
            _identity(member),
            {"members": [], "schools": [], "school_ids": set()},
        )
        person["members"].append(member)
        # The same school can legitimately appear twice for one person (a
        # roster row and a preschool-team row), so schools are deduped.
        if school.id not in person["school_ids"]:
            person["school_ids"].add(school.id)
            person["schools"].append(school)

    collapsed = []
    for person in people.values():
        members = person["members"]
        schools = sorted(person["schools"], key=lambda s: s.short_name or s.name)
        title = _first(*(m.title for m in members))
        department = _first(*(m.department for m in members))
        affiliation, is_district_wide = _affiliation(schools, type_totals)
        haystack = " ".join(
            part.lower()
            for part in (
                members[0].full_name,
                title,
                department,
                members[0].email,
                affiliation,
                *(s.name for s in schools),
                *(s.short_name for s in schools),
            )
            if part
        )
        collapsed.append(
            {
                "id": members[0].id,
                "full_name": members[0].full_name,
                "title": title,
                "role": _first(*(m.role for m in members)),
                "department": department,
                "email": _first(*(m.email for m in members)),
                "phone": _first(*(m.phone for m in members)),
                "category": classify_directory_category(title, department),
                "schools": schools,
                "school_slugs": {s.slug for s in schools},
                "school_ids": person["school_ids"],
                "school_types": {s.school_type for s in schools},
                "affiliation": affiliation,
                "is_district_wide": is_district_wide,
                "haystack": haystack,
            }
        )
    collapsed.sort(key=lambda p: p["full_name"])

    tokens = [t for t in (q or "").lower().split() if t]
    if tokens:
        collapsed = [p for p in collapsed if _matches(p, tokens)]
    if school_id:
        # Same id-or-slug courtesy as routers/schools.py:resolve_school, so
        # a link built from a slug works here too.
        collapsed = [p for p in collapsed if school_id in p["school_ids"] or school_id in p["school_slugs"]]
    if school_type:
        collapsed = [p for p in collapsed if school_type in p["school_types"]]

    counts: dict[str, int] = {}
    for person in collapsed:
        counts[person["category"]] = counts.get(person["category"], 0) + 1
    facets = [
        DirectoryFacetOut(key=key, label=label, count=counts.get(key, 0))
        for key, label in DIRECTORY_CATEGORIES
        if counts.get(key, 0) > 0
    ]

    if category:
        collapsed = [p for p in collapsed if p["category"] == category]

    page = collapsed[offset : offset + limit]
    return DirectoryPageOut(
        total=len(collapsed),
        limit=limit,
        offset=offset,
        items=[
            DirectoryStaffOut(
                id=p["id"],
                full_name=p["full_name"],
                title=p["title"],
                role=p["role"],
                department=p["department"],
                email=p["email"],
                phone=p["phone"],
                category=p["category"],
                affiliation=p["affiliation"],
                is_district_wide=p["is_district_wide"],
                schools=[
                    DirectorySchoolOut(
                        id=s.id, slug=s.slug, name=s.name, short_name=s.short_name, school_type=s.school_type
                    )
                    for s in p["schools"]
                ],
            )
            for p in page
        ],
        categories=facets,
    )
