from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, SchoolContentItem
from scheduler.registry import register_job
from services.marking_period import fetch_marking_period_page


@register_job(
    kind="marking_period.scan",
    default_name="Marking period dates scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh
    description="Parses the district's interim/marking-period/report-card dates page, per school tier.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    if not district_id:
        return "no district_id in params - nothing to do"

    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        return f"district {district_id} no longer exists"
    if not district.marking_period_url:
        return "district has no marking_period_url configured"

    dates = await fetch_marking_period_page(district.marking_period_url)
    if not dates:
        return "WARNING[no_marking_period_dates]: no marking-period dates found - the page's table structure may have changed"

    existing_by_uid = {
        d.external_uid: d
        for d in (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.district_id == district_id,
                    SchoolContentItem.source == "marking_period",
                    SchoolContentItem.external_uid.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    }

    created = updated = 0
    for entry in dates:
        row = existing_by_uid.get(entry["external_uid"])
        if row:
            row.title = entry["title"]
            row.start_date = entry["start_date"]
            updated += 1
            continue
        db.add(
            SchoolContentItem(
                scope="district",
                district_id=district_id,
                category="deadline",
                title=entry["title"],
                start_date=entry["start_date"],
                is_all_day=True,
                source="marking_period",
                external_uid=entry["external_uid"],
                applies_to_school_types=[entry["school_type"]],
            )
        )
        created += 1

    return f"marking period dates: {created} new, {updated} updated, {len(dates)} total across school tiers"
