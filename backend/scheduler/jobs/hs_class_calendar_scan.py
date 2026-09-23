from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem
from scheduler.registry import register_job
from services.hs_class_calendar import fetch_school_calendar


@register_job(
    kind="hs_class_calendar.scan",
    default_name="HS activities calendar scan",
    default_cron="0 */12 * * *",  # a public-source scan, same cadence as the district calendar
    description="Fetches a high school's own public Google Calendar (.ics) - club/interest meetings, games, and other student-life events. Tagged source=school_ics and off by default in the general calendar (see docs/HS_CLASS_PAGES_DESIGN.md).",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.activities_calendar_ics_url:
        return "school has no activities_calendar_ics_url configured"

    events = await fetch_school_calendar(school.activities_calendar_ics_url)
    if not events:
        return "WARNING[no_ics_events]: no events found in the school's activities calendar feed"

    existing_by_uid = {
        row.external_uid: row
        for row in (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.school_id == school_id,
                    SchoolContentItem.source == "school_ics",
                    SchoolContentItem.external_uid.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    }

    created = updated = 0
    for event in events:
        row = existing_by_uid.get(event["external_uid"])
        if row:
            row.title = event["title"]
            row.description = event["description"]
            row.start_date = event["start_date"]
            row.end_date = event["end_date"]
            row.is_all_day = event["is_all_day"]
            updated += 1
            continue
        db.add(
            SchoolContentItem(
                scope="school",
                school_id=school_id,
                category="event",
                title=event["title"],
                description=event["description"],
                start_date=event["start_date"],
                end_date=event["end_date"],
                is_all_day=event["is_all_day"],
                source="school_ics",
                external_uid=event["external_uid"],
            )
        )
        created += 1

    return f"school activities calendar: {created} new, {updated} updated, {len(events)} total"
