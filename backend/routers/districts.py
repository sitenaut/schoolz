from fastapi import APIRouter, Depends, HTTPException, Request, status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from auth import get_optional_user, require_permission, sees_scan_internals
from database import get_db
from models import District, DistrictTransportation, ScheduledJob, User
from scheduler.cron import public_scan_cron
from scheduler.job_names import district_job_name
from schemas import (
    DistrictCreate,
    DistrictOut,
    DistrictSummaryOut,
    DistrictTransportationOut,
    DistrictUpdate,
    ScheduledJobOut,
)

router = APIRouter(prefix="/districts", tags=["districts"])



async def _ensure_lunch_menu_job(db: AsyncSession, district: District, user: User) -> None:
    """The district's menu scan, the first time it has a food-services menu
    URL - on create, on a PATCH that adds one, or on a re-import."""
    if district.scheduled_job_id or not district.food_services_menu_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="lunch_menu.scan",
        name=district_job_name("Lunch menu scan", district),
        cron_expr=public_scan_cron("lunch_menu.scan", district.id),
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.scheduled_job_id = job.id


async def _ensure_calendar_scan_job(db: AsyncSession, district: District, user: User) -> None:
    """Auto-creates the recurring district-calendar scan the first time a
    district gets an ics_feeds entry - mirrors the lunch_menu.scan pattern."""
    if district.calendar_scan_job_id or not district.ics_feeds:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="district_calendar.scan",
        name=district_job_name("District calendar scan", district),
        cron_expr=public_scan_cron("district_calendar.scan", district.id),
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
        name=district_job_name("Marking period dates scan", district),
        cron_expr=public_scan_cron("marking_period.scan", district.id),
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
        name=district_job_name("Preschool locations scan", district),
        cron_expr=public_scan_cron("preschool_locations.scan", district.id),
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
        name=district_job_name("Preschool team scan", district),
        cron_expr=public_scan_cron("preschool_team.scan", district.id),
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
        name=district_job_name("High school day rotation scan", district),
        cron_expr=public_scan_cron("hs_rotation.scan", district.id),
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.hs_rotation_job_id = job.id


async def _ensure_calendar_pdf_job(db: AsyncSession, district: District, user: User) -> None:
    if district.calendar_pdf_job_id or not district.calendar_pdf_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="district_calendar_pdf.scan",
        name=district_job_name("District calendar PDF scan", district),
        cron_expr=public_scan_cron("district_calendar_pdf.scan", district.id),
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.calendar_pdf_job_id = job.id


async def _ensure_transportation_job(db: AsyncSession, district: District, user: User) -> None:
    if district.transportation_job_id or not district.transportation_url:
        return
    job = ScheduledJob(
        owner_user_id=user.id,
        kind="transportation.scan",
        name=district_job_name("Transportation scan", district),
        cron_expr=public_scan_cron("transportation.scan", district.id),
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
        name=district_job_name("SchoolCafé menu scan", district),
        cron_expr=public_scan_cron("schoolcafe_menu.scan", district.id),
        params={"district_id": district.id},
        enabled=True,
    )
    db.add(job)
    await db.flush()
    district.schoolcafe_job_id = job.id


async def _jobs_by_id(db: AsyncSession, districts: list[District]) -> dict[str, ScheduledJobOut]:
    # One query for every district's jobs. One per job per district was ~70
    # sequential round trips, 1.2-1.6s per GET /districts on prod.
    ids = {j for d in districts for j in (d.scheduled_job_id, d.calendar_scan_job_id, d.marking_period_job_id) if j}
    if not ids:
        return {}
    rows = (await db.execute(select(ScheduledJob).where(ScheduledJob.id.in_(ids)))).scalars().all()
    return {job.id: ScheduledJobOut.model_validate(job) for job in rows}


async def _to_out(db: AsyncSession, district: District) -> DistrictOut:
    return _out(district, await _jobs_by_id(db, [district]))


def _out(district: District, jobs: dict[str, ScheduledJobOut]) -> DistrictOut:
    return DistrictOut(
        id=district.id,
        name=district.name,
        state=district.state,
        website_url=district.website_url,
        food_services_menu_url=district.food_services_menu_url,
        ics_feeds=district.ics_feeds,
        towns=district.towns or [],
        schoolcafe_shortname=district.schoolcafe_shortname,
        marking_period_url=district.marking_period_url,
        preschool_locations_url=district.preschool_locations_url,
        preschool_team_url=district.preschool_team_url,
        hs_rotation_url=district.hs_rotation_url,
        calendar_pdf_url=district.calendar_pdf_url,
        transportation_url=district.transportation_url,
        uses_google_classroom=district.uses_google_classroom,
        genesis_url=district.genesis_url,
        created_at=district.created_at,
        scheduled_job=jobs.get(district.scheduled_job_id),
        calendar_scan_job=jobs.get(district.calendar_scan_job_id),
        marking_period_job=jobs.get(district.marking_period_job_id),
    )


@router.get("/summary", response_model=list[DistrictSummaryOut])
async def list_district_summaries(db: AsyncSession = Depends(get_db)):
    return (await db.execute(select(District).order_by(District.name))).scalars().all()


@router.get("", response_model=list[DistrictOut])
async def list_districts(
    request: Request, user: User | None = Depends(get_optional_user), db: AsyncSession = Depends(get_db)
):
    districts = list((await db.execute(select(District).order_by(District.name))).scalars().all())
    jobs = await _jobs_by_id(db, districts)
    if not await sees_scan_internals(request, db, user, "schools.manage"):
        jobs = {job_id: job.without_internals() for job_id, job in jobs.items()}
    return [_out(d, jobs) for d in districts]


@router.post("", response_model=DistrictOut, status_code=status.HTTP_201_CREATED)
async def create_district(payload: DistrictCreate, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    existing = await db.execute(select(District).where(District.name == payload.name, District.state == payload.state))
    if existing.scalar_one_or_none():
        raise HTTPException(status.HTTP_409_CONFLICT, f"A district with that name already exists in {payload.state}")

    district = District(
        name=payload.name,
        state=payload.state,
        website_url=payload.website_url,
        food_services_menu_url=payload.food_services_menu_url,
        ics_feeds=[f.model_dump() for f in payload.ics_feeds],
        towns=payload.towns,
        schoolcafe_shortname=payload.schoolcafe_shortname,
        marking_period_url=payload.marking_period_url,
        preschool_locations_url=payload.preschool_locations_url,
        preschool_team_url=payload.preschool_team_url,
        hs_rotation_url=payload.hs_rotation_url,
        calendar_pdf_url=payload.calendar_pdf_url,
        transportation_url=payload.transportation_url,
        uses_google_classroom=payload.uses_google_classroom,
        genesis_url=payload.genesis_url or None,
    )
    db.add(district)
    await db.flush()

    await _ensure_lunch_menu_job(db, district, user)
    await _ensure_calendar_scan_job(db, district, user)
    await _ensure_marking_period_job(db, district, user)
    await _ensure_preschool_locations_job(db, district, user)
    await _ensure_preschool_team_job(db, district, user)
    await _ensure_hs_rotation_job(db, district, user)
    await _ensure_calendar_pdf_job(db, district, user)
    await _ensure_transportation_job(db, district, user)
    await _ensure_schoolcafe_job(db, district, user)

    await db.commit()
    await db.refresh(district)
    return await _to_out(db, district)


@router.patch("/{district_id}", response_model=DistrictOut)
async def update_district(
    district_id: str, payload: DistrictUpdate, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)
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
    if payload.calendar_pdf_url is not None:
        district.calendar_pdf_url = payload.calendar_pdf_url
    if payload.transportation_url is not None:
        district.transportation_url = payload.transportation_url
    if payload.uses_google_classroom is not None:
        district.uses_google_classroom = payload.uses_google_classroom
    if payload.genesis_url is not None:
        district.genesis_url = payload.genesis_url or None
    await _ensure_lunch_menu_job(db, district, user)
    await _ensure_calendar_scan_job(db, district, user)
    await _ensure_marking_period_job(db, district, user)
    await _ensure_preschool_locations_job(db, district, user)
    await _ensure_preschool_team_job(db, district, user)
    await _ensure_hs_rotation_job(db, district, user)
    await _ensure_calendar_pdf_job(db, district, user)
    await _ensure_transportation_job(db, district, user)
    await _ensure_schoolcafe_job(db, district, user)
    await db.commit()
    await db.refresh(district)
    return await _to_out(db, district)


@router.post("/{district_id}/run-now")
async def run_district_menu_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.scheduled_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked menu-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.scheduled_job_id)
    return {"status": "started"}


@router.post("/{district_id}/calendar/run-now")
async def run_district_calendar_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.calendar_scan_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked calendar-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.calendar_scan_job_id)
    return {"status": "started"}


@router.post("/{district_id}/marking-period/run-now")
async def run_marking_period_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.marking_period_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked marking-period-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.marking_period_job_id)
    return {"status": "started"}


@router.post("/{district_id}/preschool-locations/run-now")
async def run_preschool_locations_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.preschool_locations_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked preschool-locations-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.preschool_locations_job_id)
    return {"status": "started"}


@router.post("/{district_id}/preschool-team/run-now")
async def run_preschool_team_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.preschool_team_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked preschool-team-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.preschool_team_job_id)
    return {"status": "started"}


@router.post("/{district_id}/hs-rotation/run-now")
async def run_hs_rotation_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.hs_rotation_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked hs-rotation-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.hs_rotation_job_id)
    return {"status": "started"}


@router.post("/{district_id}/calendar-pdf/run-now")
async def run_calendar_pdf_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.calendar_pdf_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked calendar-pdf-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.calendar_pdf_job_id)
    return {"status": "started"}


@router.post("/{district_id}/transportation/run-now")
async def run_transportation_scan_now(district_id: str, user: User = Depends(require_permission("schools.manage")), db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(District).where(District.id == district_id))
    district = result.scalar_one_or_none()
    if not district or not district.transportation_job_id:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "District has no linked transportation-scan job")

    from scheduler.runner import run_job_now

    await run_job_now(district.transportation_job_id)
    return {"status": "started"}


@router.get("/{district_id}/transportation", response_model=DistrictTransportationOut | None)
async def get_district_transportation(district_id: str, db: AsyncSession = Depends(get_db)):
    """Public. Null until the district's transportation scan has run."""
    result = await db.execute(select(DistrictTransportation).where(DistrictTransportation.district_id == district_id))
    return result.scalar_one_or_none()
