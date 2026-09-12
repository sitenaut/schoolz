from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem
from scheduler.registry import register_job
from services.special_events import discover_calendar_pdf_urls, parse_special_events_pdf


@register_job(
    kind="special_events.scan",
    default_name="Special events calendar scan",
    default_cron="0 8 * * 1",  # weekly - a themed monthly calendar, not something that changes daily
    description="Discovers and parses a school's own monthly 'special events' calendar PDF (spirit days, its own closures).",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.special_events_calendar_url:
        return "school has no special_events_calendar_url configured"

    discovered = await discover_calendar_pdf_urls(school.special_events_calendar_url)
    if not discovered:
        return "WARNING[no_calendar_found]: no special-events calendar PDF found for this month or next"

    new_pdfs = 0
    created = 0
    for year, month, pdf_url in discovered:
        # One check per PDF, not per item: an unchanged month's calendar
        # shouldn't cost another vision/tool-use call every week just to
        # re-discover the same already-stored items.
        already_processed = await db.execute(
            select(SchoolContentItem).where(SchoolContentItem.school_id == school.id, SchoolContentItem.link_url == pdf_url)
        )
        if already_processed.scalars().first():
            continue

        items = await parse_special_events_pdf(pdf_url, year, month)
        new_pdfs += 1
        for item in items:
            existing = await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.scope == "school",
                    SchoolContentItem.school_id == school.id,
                    SchoolContentItem.category == "event",
                    SchoolContentItem.title == item["title"],
                    SchoolContentItem.start_date == item["date"],
                    SchoolContentItem.is_current.is_(True),
                )
            )
            if existing.scalars().first():
                continue
            db.add(
                SchoolContentItem(
                    scope="school",
                    school_id=school.id,
                    category="event",
                    title=item["title"],
                    description=item.get("note"),
                    start_date=item["date"],
                    is_all_day=True,
                    link_url=pdf_url,
                )
            )
            created += 1

    if new_pdfs == 0:
        return f"found {len(discovered)} calendar(s), all already processed"
    return f"found {len(discovered)} calendar(s), parsed {new_pdfs} new, extracted {created} item(s)"
