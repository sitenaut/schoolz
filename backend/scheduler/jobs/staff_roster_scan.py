from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, StaffMember
from scheduler.registry import register_job
from services.staff_roles import classify_role
from services.staff_roster import fetch_roster


@register_job(
    kind="staff_roster.scan",
    default_name="Staff roster scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh like the other non-Smore scans
    description="Fetches and parses a school's staff directory into StaffMember records.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.website_url:
        return "school has no website_url configured"

    roster = await fetch_roster(school.website_url)

    existing = (await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))).scalars().all()
    existing_by_constituent = {s.source_constituent_id: s for s in existing}

    created = updated = 0
    now = datetime.now(timezone.utc)
    for entry in roster:
        row = existing_by_constituent.get(entry["constituent_id"])
        if row:
            row.full_name = entry["full_name"]
            row.title = entry["title"]
            row.role = classify_role(entry["title"])
            row.department = entry["department"]
            row.email = entry["email"]
            row.phone = entry["phone"]
            row.last_synced_at = now
            updated += 1
        else:
            db.add(
                StaffMember(
                    school_id=school.id,
                    source_constituent_id=entry["constituent_id"],
                    full_name=entry["full_name"],
                    title=entry["title"],
                    role=classify_role(entry["title"]),
                    department=entry["department"],
                    email=entry["email"],
                    phone=entry["phone"],
                )
            )
            created += 1

    if not roster:
        return (
            f"WARNING[no_staff_found]: no staff found at {school.website_url} - site may use a directory "
            "structure this parser doesn't recognize (or genuinely has no public directory)"
        )
    return f"roster: {created} new, {updated} updated, {len(roster)} total"
