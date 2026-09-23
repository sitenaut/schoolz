from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School
from scheduler.registry import register_job
from services.hs_activities_site import scan_activities_site


@register_job(
    kind="hs_activities_site.scan",
    default_name="HS activities site scan",
    default_cron="0 */12 * * *",  # a public-source scan; content-hash-free for now, so this stays cheap per run
    description="Crawls a high school's own Google Sites activities microsite (class pages, FAQs, orientation letters) and extracts grad-year-tagged content. See docs/HS_CLASS_PAGES_DESIGN.md.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.activities_site_url:
        return "school has no activities_site_url configured"

    return await scan_activities_site(db, school)
