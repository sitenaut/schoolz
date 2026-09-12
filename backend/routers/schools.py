from datetime import datetime

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_current_user, require_admin
from database import get_db
from models import District, DistrictTransportation, GuardianStudentLink, LunchMenu, LunchMenuItem, SaccProgram, ScheduledJob, School, SchoolContentItem, SchoolDocument, SmoreNewsletter, StaffMember, Student, User, derive_school_short_name, slugify
from schemas import LunchMenuItemOut, LunchMenuOut, SaccProgramOut, SchoolContentItemOut, SchoolCreate, SchoolDocumentOut, SchoolOut, SchoolTodayOut, SchoolUpdate, SmoreNewsletterOut, StaffMemberOut, DistrictTransportationOut, SchoolLateBusOut, SchoolTransportationOut
from services.school_today import build_today, resolve_lunch_menu
from services.transportation import late_bus_for_school
from routers.smore_newsletters import _to_out as _newsletter_to_out

router = APIRouter(prefix="/schools", tags=["schools"])

# All of these scan public sources (a school's own site, not Smore) - kept
# fresh on a 12h cadence rather than the weekly/monthly cadence that was
# here originally.
_STAFF_ROSTER_CRON = "0 */12 * * *"
_DOCUMENTS_SCAN_CRON = "0 */12 * * *"
_SCHOOL_INFO_CRON = "0 */12 * * *"


async def _ensure_staff_roster_job(db: AsyncSession, school: School, user: User) -> None:
    """Auto-creates the recurring staff-roster scan the first time a school
    gets a website_url - mirrors the SmoreNewsletter/District pattern."""
    if school.staff_roster_job_id or not school.website_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="staff_roster.scan",
        name=f"Staff roster scan: {school.name}",
        cron_expr=_STAFF_ROSTER_CRON,
        params={"school_id": school.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    school.staff_roster_job_id = job.id


async def _ensure_documents_scan_job(db: AsyncSession, school: School, user: User) -> None:
    """Auto-creates the recurring documents scan (handbook discovery) the
    first time a school gets a website_url - runs even for schools whose
    handbook only ever surfaces via Smore, since the job also checks that."""
    if school.documents_scan_job_id or not school.website_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="documents.scan",
        name=f"Documents scan: {school.name}",
        cron_expr=_DOCUMENTS_SCAN_CRON,
        params={"school_id": school.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    school.documents_scan_job_id = job.id


async def _ensure_school_info_job(db: AsyncSession, school: School, user: User) -> None:
    """Auto-creates the recurring school-info scan (address/main_phone from
    the school's own site) the first time a school gets a website_url."""
    if school.school_info_job_id or not school.website_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="school_info.scan",
        name=f"School info scan: {school.name}",
        cron_expr=_SCHOOL_INFO_CRON,
        params={"school_id": school.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    school.school_info_job_id = job.id


async def _ensure_special_events_job(db: AsyncSession, school: School, user: User) -> None:
    """Auto-creates the recurring special-events-calendar scan the first
    time a school gets a special_events_calendar_url - unlike
    website_url-triggered scans, this is opt-in per school (most schools
    have no such page at all; set by hand once confirmed real, as with
    Chesterbrook Academy)."""
    if school.special_events_scan_job_id or not school.special_events_calendar_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="special_events.scan",
        name=f"Special events scan: {school.name}",
        cron_expr="0 8 * * 1",
        params={"school_id": school.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    school.special_events_scan_job_id = job.id


async def _unique_slug(db: AsyncSession, base_text: str) -> str:
    base = slugify(base_text)
    slug = base
    suffix = 2
    while (await db.execute(select(School).where(School.slug == slug))).scalar_one_or_none():
        slug = f"{base}-{suffix}"
        suffix += 1
    return slug


async def resolve_school(school_id: str, db: AsyncSession = Depends(get_db)) -> School:
    """Path param is either a School.id (UUID) or its slug - lets a
    school's page be shared as a real URL (/schools/bret-harte-elementary)
    while every existing id-based link/API call keeps working unchanged."""
    result = await db.execute(select(School).where(or_(School.id == school_id, School.slug == school_id)))
    school = result.scalar_one_or_none()
    if not school:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "School not found")
    return school


@router.get("", response_model=list[SchoolOut])
async def list_schools(db: AsyncSession = Depends(get_db)):
    """Public - the whole shared school directory is meant to be
    browsable/bookmarkable without an account."""
    result = await db.execute(select(School).order_by(School.name))
    return result.scalars().all()


@router.get("/mine", response_model=list[SchoolOut])
async def list_my_schools(user: User = Depends(get_current_user), db: AsyncSession = Depends(get_db)):
    """Schools attended by any student on the current guardian's own
    profile - a filtered view over the same shared /schools data."""
    school_ids = (
        select(Student.school_id)
        .join(GuardianStudentLink, GuardianStudentLink.student_id == Student.id)
        .where(GuardianStudentLink.guardian_user_id == user.id, Student.school_id.is_not(None))
        .distinct()
    )
    result = await db.execute(select(School).where(School.id.in_(school_ids)).order_by(School.name))
    return result.scalars().all()


@router.post("", response_model=SchoolOut, status_code=status.HTTP_201_CREATED)
async def create_school(payload: SchoolCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    district_name = None
    if payload.district_id:
        district = (await db.execute(select(District).where(District.id == payload.district_id))).scalar_one_or_none()
        district_name = district.name if district else None

    short_name = payload.short_name or derive_school_short_name(payload.name, district_name)
    school = School(
        name=payload.name,
        slug=await _unique_slug(db, short_name or payload.name),
        short_name=short_name,
        district_id=payload.district_id,
        school_type=payload.school_type,
        address=payload.address,
        main_phone=payload.main_phone,
        website_url=payload.website_url,
        created_by_user_id=user.id,
    )
    db.add(school)
    await db.flush()
    await _ensure_staff_roster_job(db, school, user)
    await _ensure_documents_scan_job(db, school, user)
    await _ensure_school_info_job(db, school, user)
    await db.commit()
    await db.refresh(school)
    return school


@router.get("/{school_id}", response_model=SchoolOut)
async def get_school(school: School = Depends(resolve_school)):
    return school


@router.patch("/{school_id}", response_model=SchoolOut)
async def update_school(
    payload: SchoolUpdate, school: School = Depends(resolve_school), user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    if payload.short_name is not None:
        school.short_name = payload.short_name
    if payload.district_id is not None:
        school.district_id = payload.district_id
    if payload.school_type is not None:
        school.school_type = payload.school_type
    if payload.website_url is not None:
        school.website_url = payload.website_url
    for field in ("start_time", "end_time", "early_dismissal_time", "delayed_opening_time", "athletics_url", "logo_url", "special_events_calendar_url"):
        value = getattr(payload, field)
        if value is not None:
            setattr(school, field, value or None)
    if payload.bell_periods is not None:
        # Plain dicts for the JSON column - payload.bell_periods is typed
        # BellPeriodEntry objects (so the request body gets validated),
        # not something the JSON column can store directly.
        school.bell_periods = {variant: [p.model_dump() for p in periods] for variant, periods in payload.bell_periods.items()}
    await _ensure_staff_roster_job(db, school, user)
    await _ensure_documents_scan_job(db, school, user)
    await _ensure_school_info_job(db, school, user)
    await _ensure_special_events_job(db, school, user)
    await db.commit()
    await db.refresh(school)
    return school


@router.get("/{school_id}/staff", response_model=list[StaffMemberOut])
async def list_school_staff(school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(StaffMember).where(StaffMember.school_id == school.id).order_by(StaffMember.full_name))
    return result.scalars().all()


@router.post("/{school_id}/staff/run-now")
async def run_staff_roster_now(school: School = Depends(resolve_school), _: User = Depends(require_admin)):
    if not school.staff_roster_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "School has no linked staff-roster job")

    from scheduler.runner import run_job_now

    run_job_now(school.staff_roster_job_id)
    return {"status": "started"}


@router.post("/{school_id}/info/run-now")
async def run_school_info_now(school: School = Depends(resolve_school), _: User = Depends(require_admin)):
    if not school.school_info_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "School has no linked school-info job")

    from scheduler.runner import run_job_now

    run_job_now(school.school_info_job_id)
    return {"status": "started"}


@router.get("/{school_id}/documents", response_model=list[SchoolDocumentOut])
async def list_school_documents(
    include_superseded: bool = False, school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)
):
    query = select(SchoolDocument).where(SchoolDocument.school_id == school.id)
    if not include_superseded:
        query = query.where(SchoolDocument.is_current.is_(True))
    query = query.order_by(SchoolDocument.doc_type, SchoolDocument.title)
    result = await db.execute(query)
    return result.scalars().all()


@router.post("/{school_id}/documents/run-now")
async def run_documents_scan_now(school: School = Depends(resolve_school), _: User = Depends(require_admin)):
    if not school.documents_scan_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "School has no linked documents-scan job")

    from scheduler.runner import run_job_now

    run_job_now(school.documents_scan_job_id)
    return {"status": "started"}


@router.post("/{school_id}/special-events/run-now")
async def run_special_events_scan_now(school: School = Depends(resolve_school), _: User = Depends(require_admin)):
    if not school.special_events_scan_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "School has no linked special-events-scan job")

    from scheduler.runner import run_job_now

    run_job_now(school.special_events_scan_job_id)
    return {"status": "started"}


@router.get("/{school_id}/today", response_model=SchoolTodayOut)
async def get_school_today(school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    """Public. Everything one Today-feed card needs in a single request:
    day status (closed/early dismissal/open, from the district feed),
    hours, rotation day, today's + next lunch, SACC, role-based contacts,
    the next few dated items, this week's strip, and any closure/early
    dismissal alerts in the next 7 days."""
    return await build_today(db, school)


@router.get("/{school_id}/transportation", response_model=SchoolTransportationOut | None)
async def get_school_transportation(school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    """Public. The district's bus info plus this school's own late-bus
    contractor (null for elementary schools, which have no late bus).
    Null altogether for a school with no district, or whose district
    hasn't been scanned yet."""
    if not school.district_id:
        return None
    row = (await db.execute(select(DistrictTransportation).where(DistrictTransportation.district_id == school.district_id))).scalar_one_or_none()
    if not row:
        return None
    late = late_bus_for_school(row.late_bus_contractors, school.name, school.short_name)
    return SchoolTransportationOut(
        district=DistrictTransportationOut.model_validate(row, from_attributes=True),
        late_bus=SchoolLateBusOut(**late) if late else None,
    )


@router.get("/{school_id}/sacc", response_model=SaccProgramOut | None)
async def get_school_sacc(school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    """Returns null for schools that don't host SACC - not every elementary
    school's family is enrolled, and middle/high schools/the district's
    Early Childhood Center don't have the program at all."""
    result = await db.execute(select(SaccProgram).where(SaccProgram.school_id == school.id))
    return result.scalar_one_or_none()


@router.get("/{school_id}/lunch-menu", response_model=LunchMenuOut | None)
async def get_school_lunch_menu(
    meal_type: str = "lunch",
    school: School = Depends(resolve_school),
    db: AsyncSession = Depends(get_db),
):
    """Looks up, in order: this school's own newsletter-embedded menu (a
    private preschool has no district PDF pipeline at all), then the
    shared district+school_type PDF-based menu - the parent never needs to
    know or visit the district's own menu page, or care which source it
    came from."""
    menu = await resolve_lunch_menu(db, school, meal_type)
    if not menu:
        return None

    items = (
        (await db.execute(select(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu.id).order_by(LunchMenuItem.menu_date)))
        .scalars()
        .all()
    )
    return LunchMenuOut(
        id=menu.id,
        school_type=menu.school_type,
        meal_type=menu.meal_type,
        period_label=menu.period_label,
        source_pdf_url=menu.source_pdf_url,
        parsed_at=menu.parsed_at,
        items=[LunchMenuItemOut.model_validate(i) for i in items],
    )


@router.get("/{school_id}/newsletters", response_model=list[SmoreNewsletterOut])
async def list_school_newsletters(school: School = Depends(resolve_school), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.school_id == school.id))
    return [await _newsletter_to_out(db, n) for n in result.scalars().all()]


@router.get("/{school_id}/content", response_model=list[SchoolContentItemOut])
async def list_school_content(
    category: str | None = None,
    q: str | None = None,
    include_superseded: bool = False,
    school: School = Depends(resolve_school),
    db: AsyncSession = Depends(get_db),
):
    """A school's own view includes both its school-scoped items and its
    district's district-scoped items (e.g. holiday closures) - a parent
    looking at their kid's school page shouldn't have to separately check
    a district page to see "school closed" days."""
    scope_filter = SchoolContentItem.school_id == school.id
    if school.district_id:
        scope_filter = or_(scope_filter, SchoolContentItem.district_id == school.district_id)
    query = select(SchoolContentItem).where(scope_filter)
    if not include_superseded:
        query = query.where(SchoolContentItem.is_current.is_(True))
    if category:
        query = query.where(SchoolContentItem.category == category)
    if q:
        like = f"%{q}%"
        query = query.where(or_(SchoolContentItem.title.ilike(like), SchoolContentItem.description.ilike(like)))
    query = query.order_by(SchoolContentItem.extracted_at.desc())
    items = (await db.execute(query)).scalars().all()
    # A district item restricted to specific school types (e.g. an
    # elementary-only rotation calendar) shouldn't show up on a middle/high
    # school's own page just because they share a district.
    return [
        i
        for i in items
        if not i.applies_to_school_types or not school.school_type or school.school_type in i.applies_to_school_types
    ]
