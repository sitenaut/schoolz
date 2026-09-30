from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School
from scheduler.registry import register_job
from services.student_bulletin import scan_bulletin


@register_job(
    kind="student_bulletin.scan",
    default_name="Student bulletin scan",
    default_cron="0 */12 * * *",
    description="Reads a school's weekly student bulletin, a Google Doc rewritten in place (Marlton Middle), into dated events. Skips the model call when the doc is unchanged.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"

    return await scan_bulletin(db, school)
