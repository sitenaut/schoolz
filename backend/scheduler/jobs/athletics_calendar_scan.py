from datetime import date, timedelta

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem
from scheduler.registry import register_job
from services.arbiter import entity_id_from_athletics_url, fetch_events

# A season runs a few months; wide enough either direction to cover a
# season already in progress and next season's early games without
# fetching a year's worth of empty months.
_WINDOW_PAST_DAYS = 30
_WINDOW_FUTURE_DAYS = 180


@register_job(
    kind="athletics_calendar.scan",
    default_name="Athletics calendar scan",
    default_cron="0 */12 * * *",  # a public-source scan, same cadence as the other calendar scans
    description=(
        "Fetches a school's game schedule from ArbiterLive (School.athletics_url, when it's a /m/team/<id> page) - "
        "every sport/level combined. Tagged source=arbiter_athletics and off by default in the general calendar "
        "(dozens of games a week would crowd out real deadlines); visible via the 'Show sports schedule' toggle."
    ),
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"

    entity_id = entity_id_from_athletics_url(school.athletics_url)
    if not entity_id:
        return "school's athletics_url isn't an ArbiterLive team page (/m/team/<id>) - nothing to fetch"

    today = date.today()
    events = await fetch_events(entity_id, today - timedelta(days=_WINDOW_PAST_DAYS), today + timedelta(days=_WINDOW_FUTURE_DAYS))
    if not events:
        return "WARNING[no_arbiter_events]: no games found on ArbiterLive for this school"

    existing_by_uid = {
        row.external_uid: row
        for row in (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.school_id == school_id,
                    SchoolContentItem.source == "arbiter_athletics",
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
                source="arbiter_athletics",
                external_uid=event["external_uid"],
            )
        )
        created += 1

    return f"athletics calendar: {created} new, {updated} updated, {len(events)} total"
