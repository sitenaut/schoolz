from datetime import datetime

from fastapi import APIRouter, Depends
from sqlalchemy import and_, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_user
from database import get_db
from models import GuardianStudentLink, School, SchoolContentItem, Student, User
from schemas import SchoolContentItemOut
from services.class_years import CLASS_PAGE_SOURCES

router = APIRouter(prefix="/calendar", tags=["calendar"])

_CALENDAR_CATEGORIES = ("event", "deadline", "initiative", "marking_period")


async def _my_school_and_district_ids(db: AsyncSession, user_id: str) -> tuple[list[str], list[str], set[str]]:
    result = await db.execute(
        select(School.id, School.district_id, School.school_type)
        .join(Student, Student.school_id == School.id)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(GuardianStudentLink.guardian_user_id == user_id)
        .distinct()
    )
    rows = result.all()
    school_ids = [r[0] for r in rows]
    district_ids = [r[1] for r in rows if r[1]]
    school_types = {r[2] for r in rows if r[2]}
    return school_ids, district_ids, school_types


async def _my_grad_years(db: AsyncSession, user_id: str) -> set[int]:
    result = await db.execute(
        select(Student.grad_year)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(GuardianStudentLink.guardian_user_id == user_id, Student.grad_year.is_not(None))
        .distinct()
    )
    return set(result.scalars().all())


def _applies_to_grad_years(item: SchoolContentItem, my_grad_years: set[int]) -> bool:
    """Same null-means-everyone shape as _applies_to_types. Only narrows
    for a signed-in guardian with a grad_year on file - an anonymous
    visitor (or one with no grad_year typed in yet) sees every class's
    items, same as the school-type filter only ever narrows when there's
    something concrete to narrow by."""
    if not item.applies_to_grad_years or not my_grad_years:
        return True
    return bool(set(item.applies_to_grad_years) & my_grad_years)


def _class_label(item: SchoolContentItem) -> str | None:
    if not item.applies_to_grad_years:
        return None
    if len(item.applies_to_grad_years) == 1:
        return f"Class of {item.applies_to_grad_years[0]}"
    years = ", ".join(str(y) for y in sorted(item.applies_to_grad_years))
    return f"Classes of {years}"


def _applies_to_types(item: SchoolContentItem, relevant_types: set[str]) -> bool:
    """A scope="district" item with applies_to_school_types set (e.g. an
    elementary-only rotation calendar) only shows up if at least one
    relevant school is that type - null/empty means it applies regardless
    of school type, same as before this filter existed."""
    if not item.applies_to_school_types:
        return True
    return bool(set(item.applies_to_school_types) & relevant_types)


@router.get("", response_model=list[SchoolContentItemOut])
async def list_calendar_items(
    start: datetime | None = None,
    end: datetime | None = None,
    school_id: str | None = None,
    school_ids: str | None = None,
    category: str | None = None,
    q: str | None = None,
    include_class_sources: bool = False,
    user: User | None = Depends(get_optional_user),
    db: AsyncSession = Depends(get_db),
):
    """Everything here is public data. A logged-in guardian with linked
    kids gets it narrowed to their own schools + district-wide items by
    default (not every school in the system, which would be mostly noise);
    an anonymous visitor (or a logged-in user with no linked schools yet)
    sees everything unfiltered instead - there's no "my schools" to narrow
    to, and the whole point of this being public is that it doesn't need
    an account to browse. An explicit school_id always narrows further,
    logged in or not.

    include_class_sources=False (the default) excludes a high school's own
    activities-calendar/announcements items - too much club-meeting-level
    detail for a district-wide view (see CLASS_PAGE_SOURCES). The Calendar
    page's "Show club & interest meetings" toggle is the one place that
    flips this on; when it's on, a signed-in guardian's own grad_year
    narrows which classes' items they see, and every remaining item gets a
    class_label badge ("Class of 2027")."""
    my_school_ids, my_district_ids, my_school_types = ([], [], set())
    my_grad_years: set[int] = set()
    if user:
        my_school_ids, my_district_ids, my_school_types = await _my_school_and_district_ids(db, user.id)
        my_grad_years = await _my_grad_years(db, user.id)

    filter_by_type = False
    if school_ids:
        # Comma-separated ids or slugs - an anonymous visitor's device-saved
        # school list (no account, so no /schools/mine to fall back on).
        wanted = [x for x in school_ids.split(",") if x]
        picked = (await db.execute(select(School).where(or_(School.id.in_(wanted), School.slug.in_(wanted))))).scalars().all()
        scope_ids = ([s.id for s in picked], list({s.district_id for s in picked if s.district_id}))
        relevant_types = {s.school_type for s in picked if s.school_type}
        filter_by_type = True
    elif school_id:
        # Narrow to one school - still include its own district's items.
        school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
        scope_ids = ([school_id], [school.district_id] if school and school.district_id else [])
        relevant_types = {school.school_type} if school and school.school_type else set()
        filter_by_type = True
    elif my_school_ids:
        scope_ids = (my_school_ids, my_district_ids)
        relevant_types = my_school_types
        filter_by_type = True
    else:
        all_school_ids = (await db.execute(select(School.id))).scalars().all()
        all_district_ids = (await db.execute(select(School.district_id).where(School.district_id.is_not(None)).distinct())).scalars().all()
        scope_ids = (all_school_ids, all_district_ids)
        relevant_types = set()

    scope_filter = or_(SchoolContentItem.school_id.in_(scope_ids[0]), SchoolContentItem.district_id.in_(scope_ids[1]))

    query = select(SchoolContentItem).where(
        scope_filter,
        SchoolContentItem.is_current.is_(True),
        SchoolContentItem.category.in_(_CALENDAR_CATEGORIES),
        SchoolContentItem.start_date.is_not(None),
    )
    if not include_class_sources:
        query = query.where(SchoolContentItem.source.not_in(CLASS_PAGE_SOURCES))
    if category:
        query = query.where(SchoolContentItem.category == category)
    if q:
        like = f"%{q}%"
        query = query.where(or_(SchoolContentItem.title.ilike(like), SchoolContentItem.description.ilike(like)))
    if start:
        # Overlaps the range. An all-day item's end_date is the ICS-style
        # exclusive day after its last day, so one ending exactly at the range
        # start (an Aug 31 in-service ending "Sep 1 00:00") doesn't overlap -
        # it used to lead September's list.
        query = query.where(
            or_(
                SchoolContentItem.start_date >= start,
                and_(SchoolContentItem.is_all_day.is_(True), SchoolContentItem.end_date > start),
                and_(SchoolContentItem.is_all_day.is_(False), SchoolContentItem.end_date >= start),
            )
        )
    if end:
        query = query.where(SchoolContentItem.start_date <= end)

    query = query.order_by(SchoolContentItem.start_date)
    items = (await db.execute(query)).scalars().all()
    if filter_by_type:
        items = [i for i in items if _applies_to_types(i, relevant_types)]
    items = [i for i in items if _applies_to_grad_years(i, my_grad_years)]

    school_ids_in_results = {i.school_id for i in items if i.school_id}
    school_names: dict[str, str] = {}
    if school_ids_in_results:
        schools = (await db.execute(select(School).where(School.id.in_(school_ids_in_results)))).scalars().all()
        school_names = {s.id: s.short_name or s.name for s in schools}

    return [
        SchoolContentItemOut.model_validate(i, from_attributes=True).model_copy(
            update={
                "school_name": school_names.get(i.school_id) if i.scope == "school" else None,
                "class_label": _class_label(i),
            }
        )
        for i in items
    ]
