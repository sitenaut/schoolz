from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School
from scheduler.registry import register_job
from services.school_events_doc import scan_events_doc


@register_job(
    kind="school_events_doc.scan",
    default_name="School events doc scan",
    default_cron="0 */12 * * *",
    description="Parses a school's own year-at-a-glance events calendar published as a Google Doc (Cherry Hill West's activities site embeds one). Deterministic, no model call.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"

    return await scan_events_doc(db, school)
