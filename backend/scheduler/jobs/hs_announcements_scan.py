from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School
from scheduler.registry import register_job
from services.hs_announcements import scan_announcements


@register_job(
    kind="hs_announcements.scan",
    default_name="HS morning announcements scan",
    # Tighter than the 12h public-source default: this source's own real
    # value is same-day content (a bus cancellation, a rescheduled club
    # meeting) that a 12h cadence would routinely miss entirely. Weekdays
    # only during the school day - the doc simply isn't appended to on
    # weekends/summer, so there's nothing to gain from scanning then, and
    # this is a real Google Doc export fetch, not a cache hit.
    default_cron="0 6-18/2 * * 1-5",
    description="Extracts club meetings, deadlines, and same-day logistics/cancellations from a high school's own running Morning Announcements Google Doc. See docs/HS_CLASS_PAGES_DESIGN.md.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.announcements_doc_url:
        return "school has no announcements_doc_url configured"

    return await scan_announcements(db, school)
