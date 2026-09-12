from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scraper_client
from models import District, School, StaffMember
from scheduler.registry import register_job
from services.staff_roles import classify_role
from services.preschool_team import parse_preschool_team


@register_job(
    kind="preschool_team.scan",
    default_name="Preschool team scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh
    description="Parses the district's central preschool administration staff, applied to every preschool-type School.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    if not district_id:
        return "no district_id in params - nothing to do"

    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        return f"district {district_id} no longer exists"
    if not district.preschool_team_url:
        return "district has no preschool_team_url configured"

    preschools = (
        await db.execute(select(School).where(School.district_id == district_id, School.school_type == "other"))
    ).scalars().all()
    if not preschools:
        return "WARNING[no_preschools_tracked]: no preschool-type (school_type='other') schools tracked yet to attach staff to"

    result = await scraper_client.fetch_html(district.preschool_team_url, wait_for_selector="a")
    team = parse_preschool_team(result["html"])
    if not team:
        return "WARNING[no_preschool_team]: no preschool team members found - the page's structure may have changed"

    now = datetime.now(timezone.utc)
    created = updated = 0
    for school in preschools:
        existing = (
            await db.execute(select(StaffMember).where(StaffMember.school_id == school.id))
        ).scalars().all()
        # Central preschool admin staff use their email as the stable id -
        # they have no Finalsite constituent id (this isn't a directory scan).
        existing_by_email = {s.source_constituent_id: s for s in existing if s.source_constituent_id.startswith("preschool-team:")}

        for member in team:
            constituent_id = f"preschool-team:{member['email']}"
            row = existing_by_email.get(constituent_id)
            if row:
                row.full_name = member["full_name"]
                row.title = member["title"]
                row.role = classify_role(member["title"])
                row.phone = member["phone"]
                row.email = member["email"]
                row.last_synced_at = now
                updated += 1
            else:
                db.add(
                    StaffMember(
                        school_id=school.id,
                        source_constituent_id=constituent_id,
                        full_name=member["full_name"],
                        title=member["title"],
                        role=classify_role(member["title"]),
                        department="Preschool Administration",
                        email=member["email"],
                        phone=member["phone"],
                    )
                )
                created += 1

    return f"preschool team: {created} new, {updated} updated, applied to {len(preschools)} preschool-type school(s)"
