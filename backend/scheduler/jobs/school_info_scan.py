from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School
from scheduler.registry import register_job
from services.school_info import discover_school_info


@register_job(
    kind="school_info.scan",
    default_name="School info scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh
    description="Fetches a school's public address and main phone number from its own site.",
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

    info = await discover_school_info(school.website_url)

    changed = []
    if info["address"] and info["address"] != school.address:
        school.address = info["address"]
        changed.append("address")
    if info["main_phone"] and info["main_phone"] != school.main_phone:
        school.main_phone = info["main_phone"]
        changed.append("main_phone")
    if info["logo_url"] and info["logo_url"] != school.logo_url:
        school.logo_url = info["logo_url"]
        changed.append("logo")

    if not info["address"] or not info["main_phone"]:
        missing = [f for f in ("address", "main_phone") if not info[f]]
        return f"WARNING: could not find {', '.join(missing)} on the school's site"

    if not changed:
        return "address and main_phone unchanged"
    return f"updated: {', '.join(changed)}"
