from datetime import datetime
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, SchoolContentItem
from scheduler.registry import register_job
from services.marking_period import fetch_marking_period_page

_ET = ZoneInfo("America/New_York")


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
            row.category = "marking_period"
            row.is_current = True
            updated += 1
            continue
        db.add(
            SchoolContentItem(
                scope="district",
                district_id=district_id,
                # Not "deadline" - a report card/interim/marking-period-end
                # date isn't something a parent has to act on, unlike a
                # real deadline (form due, registration closes). Labeled
                # "grading" on the frontend (components/today.tsx's ItemTag).
                category="marking_period",
                title=entry["title"],
                start_date=entry["start_date"],
                is_all_day=True,
                source="marking_period",
                external_uid=entry["external_uid"],
                applies_to_school_types=[entry["school_type"]] if entry["school_type"] else None,
            )
        )
        created += 1

    retired = _retire_unlisted(dates, existing_by_uid)
    return (
        f"marking period dates: {created} new, {updated} updated, {retired} no longer listed, "
        f"{len(dates)} total across school tiers"
    )


def _retire_unlisted(dates: list[dict], existing_by_uid: dict[str, SchoolContentItem]) -> int:
    """A date the page stopped listing (corrected, or replaced by next year's)
    kept showing as upcoming, since the uid carries the date. Retire upcoming
    rows of the tiers this read found; a tier missing from the read (its table
    no longer parses) keeps its rows. Retired, not deleted, like the district
    calendar's (district_calendar_scan._retire_vanished): a date that comes
    back is made current again above."""
    seen = {entry["external_uid"] for entry in dates}
    tiers = {entry["school_type"] for entry in dates}
    today = datetime.now(_ET).date()
    retired = 0
    for uid, row in existing_by_uid.items():
        tier = row.applies_to_school_types[0] if row.applies_to_school_types else None
        if uid in seen or tier not in tiers or not row.is_current or row.start_date is None:
            continue
        if row.start_date.astimezone(_ET).date() >= today:
            row.is_current = False
            retired += 1
    return retired
