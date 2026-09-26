from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import require_admin
from database import get_db
from models import District, DistrictTransportation, ScheduledJob, User
from schemas import DistrictCreate, DistrictOut, DistrictSummaryOut, DistrictUpdate, ScheduledJobOut, DistrictTransportationOut

router = APIRouter(prefix="/districts", tags=["districts"])

_DEFAULT_CRON = "0 */12 * * *"  # every 12h - a public-source scan, kept fresh like the other non-Smore scans


async def _ensure_calendar_scan_job(db: AsyncSession, district: District, user: User) -> None:
    """Auto-creates the recurring district-calendar scan the first time a
    district gets an ics_feeds entry - mirrors the lunch_menu.scan pattern."""
    if district.calendar_scan_job_id or not district.ics_feeds:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="district_calendar.scan",
        name=f"District calendar scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.calendar_scan_job_id = job.id


async def _ensure_marking_period_job(db: AsyncSession, district: District, user: User) -> None:
    """Auto-creates the recurring marking-period-dates scan the first time
    a district gets a marking_period_url."""
    if district.marking_period_job_id or not district.marking_period_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="marking_period.scan",
        name=f"Marking period dates scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.marking_period_job_id = job.id


async def _ensure_preschool_locations_job(db: AsyncSession, district: District, user: User) -> None:
    if district.preschool_locations_job_id or not district.preschool_locations_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="preschool_locations.scan",
        name=f"Preschool locations scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.preschool_locations_job_id = job.id


async def _ensure_preschool_team_job(db: AsyncSession, district: District, user: User) -> None:
    if district.preschool_team_job_id or not district.preschool_team_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="preschool_team.scan",
        name=f"Preschool team scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.preschool_team_job_id = job.id


async def _ensure_hs_rotation_job(db: AsyncSession, district: District, user: User) -> None:
    if district.hs_rotation_job_id or not district.hs_rotation_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="hs_rotation.scan",
        name=f"High school day rotation scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.hs_rotation_job_id = job.id


async def _ensure_transportation_job(db: AsyncSession, district: District, user: User) -> None:
    if district.transportation_job_id or not district.transportation_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="transportation.scan",
        name=f"Transportation scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.transportation_job_id = job.id


async def _ensure_schoolcafe_job(db: AsyncSession, district: District, user: User) -> None:
    if district.schoolcafe_job_id or not district.schoolcafe_shortname:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="schoolcafe_menu.scan",
        name=f"SchoolCafé menu scan: {district.name}",
        cron_expr=_DEFAULT_CRON,
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.schoolcafe_job_id = job.id


async def _to_out(db: AsyncSession, district: District) -> DistrictOut:
    job = None
    if district.scheduled_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == district.scheduled_job_id))
        job_row = result.scalar_one_or_none()
        if job_row:
            job = ScheduledJobOut.model_validate(job_row)
    calendar_job = None
    if district.calendar_scan_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == district.calendar_scan_job_id))
        job_row = result.scalar_one_or_none()
        if job_row:
            calendar_job = ScheduledJobOut.model_validate(job_row)
    marking_period_job = None
    if district.marking_period_job_id:
        result = await db.execute(select(ScheduledJob).where(ScheduledJob.id == district.marking_period_job_id))
        job_row = result.scalar_one_or_none()
        if job_row:
            marking_period_job = ScheduledJobOut.model_validate(job_row)
    return DistrictOut(
        id=district.id,
        name=district.name,
        website_url=district.website_url,
        food_services_menu_url=district.food_services_menu_url,
        ics_feeds=district.ics_feeds,
        towns=district.towns or [],
        schoolcafe_shortname=district.schoolcafe_shortname,
        marking_period_url=district.marking_period_url,
        preschool_locations_url=district.preschool_locations_url,
        preschool_team_url=district.preschool_team_url,
        hs_rotation_url=district.hs_rotation_url,
        transportation_url=district.transportation_url,
        created_at=district.created_at,
        scheduled_job=job,
        calendar_scan_job=calendar_job,
        marking_period_job=marking_period_job,
    )


@router.get("/summary", response_model=list[DistrictSummaryOut])
async def list_district_summaries(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(District).order_by(District.name))).scalars().all()


@router.get("", response_model=list[DistrictOut])
async def list_districts(db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).order_by(District.name))
    return [await _to_out(db, d) for d in result.scalars().all()]


@router.post("", response_model=DistrictOut, status_code=status.HTTP_201_CREATED)
async def create_district(payload: DistrictCreate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(District).where(District.name == payload.name))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, "A district with that name already exists")

    district = District(
        name=payload.name,
        website_url=payload.website_url,
        food_services_menu_url=payload.food_services_menu_url,
        ics_feeds=[f.model_dump() for f in payload.ics_feeds],
        towns=payload.towns,
        schoolcafe_shortname=payload.schoolcafe_shortname,
        marking_period_url=payload.marking_period_url,
        preschool_locations_url=payload.preschool_locations_url,
        preschool_team_url=payload.preschool_team_url,
        hs_rotation_url=payload.hs_rotation_url,
        transportation_url=payload.transportation_url,
    )
    db.add(district)
    await db.flush()

    if payload.food_services_menu_url:
        job = ScheduledJob(
            owner_user_id=user.id,
            kind="lunch_menu.scan",
            name=f"Lunch menu scan: {payload.name}",
            cron_expr=_DEFAULT_CRON,
            params={"district_id": district.id},
            enabled=True,
        )
        db.add(job)
        await db.flush()
        district.scheduled_job_id = job.id

    await _ensure_calendar_scan_job(db, district, user)
    await _ensure_marking_period_job(db, district, user)
    await _ensure_preschool_locations_job(db, district, user)
    await _ensure_preschool_team_job(db, district, user)
    await _ensure_hs_rotation_job(db, district, user)
    await _ensure_transportation_job(db, district, user)
    await _ensure_schoolcafe_job(db, district, user)

    await db.commit()
    await db.refresh(district)
    return await _to_out(db, district)


@router.patch("/{district_id}", response_model=DistrictOut)
async def update_district(
    district_id: str, payload: DistrictUpdate, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)
):
    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "District not found")
    if payload.website_url is not None:
        district.website_url = payload.website_url
    if payload.food_services_menu_url is not None:
        district.food_services_menu_url = payload.food_services_menu_url
    if payload.ics_feeds is not None:
        district.ics_feeds = [f.model_dump() for f in payload.ics_feeds]
    if payload.towns is not None:
        district.towns = payload.towns
    if payload.schoolcafe_shortname is not None:
        district.schoolcafe_shortname = payload.schoolcafe_shortname or None
    if payload.marking_period_url is not None:
        district.marking_period_url = payload.marking_period_url
    if payload.preschool_locations_url is not None:
        district.preschool_locations_url = payload.preschool_locations_url
    if payload.preschool_team_url is not None:
        district.preschool_team_url = payload.preschool_team_url
    if payload.hs_rotation_url is not None:
        district.hs_rotation_url = payload.hs_rotation_url
    if payload.transportation_url is not None:
        district.transportation_url = payload.transportation_url
    await _ensure_calendar_scan_job(db, district, user)
    await _ensure_marking_period_job(db, district, user)
    await _ensure_preschool_locations_job(db, district, user)
    await _ensure_preschool_team_job(db, district, user)
    await _ensure_hs_rotation_job(db, district, user)
    await _ensure_transportation_job(db, district, user)
    await _ensure_schoolcafe_job(db, district, user)
    await db.commit()
    await db.refresh(district)
    return await _to_out(db, district)


@router.post("/{district_id}/run-now")
async def run_district_menu_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.scheduled_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked menu-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.scheduled_job_id)
    return {"status": "started"}


@router.post("/{district_id}/calendar/run-now")
async def run_district_calendar_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.calendar_scan_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked calendar-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.calendar_scan_job_id)
    return {"status": "started"}


@router.post("/{district_id}/marking-period/run-now")
async def run_marking_period_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.marking_period_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked marking-period-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.marking_period_job_id)
    return {"status": "started"}


@router.post("/{district_id}/preschool-locations/run-now")
async def run_preschool_locations_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.preschool_locations_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked preschool-locations-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.preschool_locations_job_id)
    return {"status": "started"}


@router.post("/{district_id}/preschool-team/run-now")
async def run_preschool_team_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.preschool_team_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked preschool-team-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.preschool_team_job_id)
    return {"status": "started"}


@router.post("/{district_id}/hs-rotation/run-now")
async def run_hs_rotation_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.hs_rotation_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked hs-rotation-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.hs_rotation_job_id)
    return {"status": "started"}


@router.post("/{district_id}/transportation/run-now")
async def run_transportation_scan_now(district_id: str, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.transportation_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked transportation-scan job")

    from scheduler.runner import run_job_now

    run_job_now(district.transportation_job_id)
    return {"status": "started"}


@router.get("/{district_id}/transportation", response_model=DistrictTransportationOut | None)
async def get_district_transportation(district_id: str, db: AsyncSession = Depends(get_db)):
    """Public. Null until the district's transportation scan has run."""
    result = await db.execute(select(DistrictTransportation).where(DistrictTransportation.district_id == district_id))
    return result.scalar_one_or_none()
