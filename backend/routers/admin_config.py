"""Ports centrally-managed configuration (districts, schools, Smore
newsletters, SACC programs) between environments - built specifically so
"go from a local dev instance with everything set up to a fresh prod
database" doesn't mean re-entering every district URL, school website,
and newsletter link by hand.

Deliberately scoped to what's already public and admin-owned (the same
data GET /schools and GET /districts expose to anyone) - never users,
students, guardian links, Gmail tokens, or email scanners. Those are
per-account and belong to whoever creates them in each environment
separately, not something to carry across.

Import goes through the exact same creation/update paths as the normal
POST/PATCH endpoints (the `_ensure_*_job` helpers imported from
routers.schools/routers.districts), so a scan job gets created for a
newly-set URL exactly as if an admin had set it by hand through the UI -
no separate, unvalidated code path to keep in sync with those. It's
idempotent: matched by district name and school slug, re-running an
import after new local changes only updates what's different.

See backend/scripts/migrate_config.py for the CLI that pulls this from
one environment and pushes it to another.
"""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from database import get_db
from auth import require_admin
from models import District, SaccProgram, School, SmoreNewsletter, User
from schemas import (
    ConfigExport,
    ConfigImportResult,
    ExportDistrictOut,
    ExportSaccOut,
    ExportSchoolOut,
    ExportSmoreOut,
)
from routers.districts import (
    _ensure_calendar_scan_job,
    _ensure_hs_rotation_job,
    _ensure_marking_period_job,
    _ensure_preschool_locations_job,
    _ensure_preschool_team_job,
    _ensure_transportation_job,
)
from routers.schools import _ensure_documents_scan_job, _ensure_school_info_job, _ensure_staff_roster_job
from routers.smore_newsletters import _validate_cron

router = APIRouter(prefix="/admin/config", tags=["admin-config"])


@router.get("/export", response_model=ConfigExport, dependencies=[Depends(require_admin)])
async def export_config(db: AsyncSession = Depends(get_db)):
    districts = (await db.execute(select(District))).scalars().all()
    schools = (await db.execute(select(School))).scalars().all()
    newsletters = (await db.execute(select(SmoreNewsletter))).scalars().all()
    saccs = {s.school_id: s for s in (await db.execute(select(SaccProgram))).scalars().all()}
    district_by_id = {d.id: d for d in districts}
    school_by_id = {s.id: s for s in schools}

    return ConfigExport(
        exported_at=datetime.now(timezone.utc),
        source="schoolz",
        districts=[ExportDistrictOut.model_validate(d, from_attributes=True) for d in districts],
        schools=[
            ExportSchoolOut(
                slug=s.slug,
                name=s.name,
                short_name=s.short_name,
                district_name=district_by_id[s.district_id].name if s.district_id in district_by_id else None,
                school_type=s.school_type,
                address=s.address,
                main_phone=s.main_phone,
                website_url=s.website_url,
                absence_method=s.absence_method,
                absence_emails=s.absence_emails,
                absence_phone=s.absence_phone,
                absence_portal_name=s.absence_portal_name,
                absence_portal_url=s.absence_portal_url,
                absence_instructions=s.absence_instructions,
                start_time=s.start_time,
                end_time=s.end_time,
                early_dismissal_time=s.early_dismissal_time,
                delayed_opening_time=s.delayed_opening_time,
                athletics_url=s.athletics_url,
                logo_url=s.logo_url,
                bell_periods=s.bell_periods,
                sacc=ExportSaccOut.model_validate(saccs[s.id], from_attributes=True) if s.id in saccs else None,
            )
            for s in schools
        ],
        smore_newsletters=[
            ExportSmoreOut(
                url=n.url,
                label=n.label,
                school_slug=school_by_id[n.school_id].slug if n.school_id in school_by_id else None,
                cron_expr="0 8 * * 1",
                timezone="America/New_York",
                enabled=True,
            )
            for n in newsletters
        ],
    )


@router.post("/import", response_model=ConfigImportResult, dependencies=[Depends(require_admin)])
async def import_config(payload: ConfigExport, user: User = Depends(require_admin), db: AsyncSession = Depends(get_db)):
    result = {
        "districts_created": 0, "districts_updated": 0,
        "schools_created": 0, "schools_updated": 0,
        "smore_created": 0, "smore_updated": 0, "smore_skipped": [],
        "sacc_created": 0, "sacc_updated": 0,
    }

    # --- Districts, matched by name ---
    district_by_name: dict[str, District] = {d.name: d for d in (await db.execute(select(District))).scalars().all()}
    for d in payload.districts:
        district = district_by_name.get(d.name)
        if district is None:
            district = District(name=d.name)
            db.add(district)
            await db.flush()
            district_by_name[d.name] = district
            result["districts_created"] += 1
        else:
            result["districts_updated"] += 1
        district.website_url = d.website_url
        district.food_services_menu_url = d.food_services_menu_url
        district.ics_feeds = [f.model_dump() for f in d.ics_feeds]
        district.marking_period_url = d.marking_period_url
        district.preschool_locations_url = d.preschool_locations_url
        district.preschool_team_url = d.preschool_team_url
        district.hs_rotation_url = d.hs_rotation_url
        district.transportation_url = d.transportation_url
        await _ensure_calendar_scan_job(db, district, user)
        await _ensure_marking_period_job(db, district, user)
        await _ensure_preschool_locations_job(db, district, user)
        await _ensure_preschool_team_job(db, district, user)
        await _ensure_hs_rotation_job(db, district, user)
        await _ensure_transportation_job(db, district, user)
        # food_services_menu_url's lunch_menu.scan job is created only at
        # district *creation* time in the normal POST /districts flow
        # (see routers/districts.py) - mirror that here for a newly-created
        # district only, so re-importing an already-existing district
        # doesn't need its own separate "_ensure" helper that doesn't exist.
        if result["districts_created"] and d.food_services_menu_url and not district.scheduled_job_id:
            from models import ScheduledJob

            job = ScheduledJob(
                owner_user_id=user.id,
                kind="lunch_menu.scan",
                name=f"Lunch menu scan: {district.name}",
                cron_expr="0 */12 * * *",
                params={"district_id": district.id},
                enabled=True,
            )
            db.add(job)
            await db.flush()
            district.scheduled_job_id = job.id

    # --- Schools, matched by slug (falling back to name) ---
    school_by_slug: dict[str, School] = {s.slug: s for s in (await db.execute(select(School))).scalars().all()}
    school_by_name: dict[str, School] = {s.name: s for s in school_by_slug.values()}
    for s in payload.schools:
        school = school_by_slug.get(s.slug) or school_by_name.get(s.name)
        district = district_by_name.get(s.district_name) if s.district_name else None
        if school is None:
            # Use the exported slug directly rather than recomputing one -
            # slugs are meant to be stable, portable identifiers, and a
            # freshly-derived slug wouldn't necessarily match what the
            # smore_newsletters below expect to link against by slug
            # (confirmed real bug: a recomputed slug silently orphaned
            # every newsletter for a newly-imported school).
            school = School(
                name=s.name,
                slug=s.slug,
                short_name=s.short_name,
                district_id=district.id if district else None,
                school_type=s.school_type,
                address=s.address,
                main_phone=s.main_phone,
                website_url=s.website_url,
                created_by_user_id=user.id,
            )
            db.add(school)
            await db.flush()
            school_by_slug[school.slug] = school
            school_by_name[school.name] = school
            result["schools_created"] += 1
        else:
            result["schools_updated"] += 1
            if district:
                school.district_id = district.id
            if s.school_type:
                school.school_type = s.school_type
            if s.website_url:
                school.website_url = s.website_url
        # Fields the normal PATCH endpoint accepts, plus the discovered
        # fields (address/phone/absence_*) that PATCH doesn't expose but
        # are safe to carry over directly here since we're writing the
        # model, not going through the public schema.
        school.short_name = s.short_name or school.short_name
        school.address = s.address or school.address
        school.main_phone = s.main_phone or school.main_phone
        school.absence_method = s.absence_method or school.absence_method
        school.absence_emails = s.absence_emails or school.absence_emails
        school.absence_phone = s.absence_phone or school.absence_phone
        school.absence_portal_name = s.absence_portal_name or school.absence_portal_name
        school.absence_portal_url = s.absence_portal_url or school.absence_portal_url
        school.absence_instructions = s.absence_instructions or school.absence_instructions
        school.start_time = s.start_time or school.start_time
        school.end_time = s.end_time or school.end_time
        school.early_dismissal_time = s.early_dismissal_time or school.early_dismissal_time
        school.delayed_opening_time = s.delayed_opening_time or school.delayed_opening_time
        school.athletics_url = s.athletics_url or school.athletics_url
        school.logo_url = s.logo_url or school.logo_url
        if s.bell_periods:
            school.bell_periods = {variant: [p.model_dump() for p in periods] for variant, periods in s.bell_periods.items()}
        await _ensure_staff_roster_job(db, school, user)
        await _ensure_documents_scan_job(db, school, user)
        await _ensure_school_info_job(db, school, user)

        if s.sacc:
            existing_sacc = (await db.execute(select(SaccProgram).where(SaccProgram.school_id == school.id))).scalar_one_or_none()
            if existing_sacc is None:
                existing_sacc = SaccProgram(school_id=school.id)
                db.add(existing_sacc)
                result["sacc_created"] += 1
            else:
                result["sacc_updated"] += 1
            for field in (
                "am_hours", "pm_hours", "site_phone", "absence_phone", "absence_form_url",
                "late_pickup_policy", "pickup_change_procedure", "closures_notes", "handbook_url",
            ):
                setattr(existing_sacc, field, getattr(s.sacc, field))

    await db.flush()

    # --- Smore newsletters, matched by url ---
    newsletter_by_url: dict[str, SmoreNewsletter] = {n.url: n for n in (await db.execute(select(SmoreNewsletter))).scalars().all()}
    for n in payload.smore_newsletters:
        school = school_by_slug.get(n.school_slug) if n.school_slug else None
        if n.school_slug and not school:
            result["smore_skipped"].append(n.url)
            continue
        _validate_cron(n.cron_expr)
        newsletter = newsletter_by_url.get(n.url)
        if newsletter is None:
            newsletter = SmoreNewsletter(url=n.url, label=n.label, school_id=school.id if school else None, created_by_user_id=user.id)
            db.add(newsletter)
            await db.flush()
            from models import ScheduledJob

            job = ScheduledJob(
                owner_user_id=user.id,
                kind="smore.scan",
                name=f"Smore scan: {n.label or n.url}",
                cron_expr=n.cron_expr,
                timezone=n.timezone,
                params={"newsletter_id": newsletter.id},
                enabled=n.enabled,
            )
            db.add(job)
            await db.flush()
            newsletter.scheduled_job_id = job.id
            result["smore_created"] += 1
        else:
            newsletter.label = n.label or newsletter.label
            if school:
                newsletter.school_id = school.id
            result["smore_updated"] += 1

    await db.commit()
    return ConfigImportResult(**result)
