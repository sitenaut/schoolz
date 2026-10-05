import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LunchMenu, LunchMenuItem, School, SchoolContentItem
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.lunch_menu import parse_menu_pdf
from services.special_events import (
    _MONTH_NAMES,
    calendar_pdfs_from_pages,
    discover_menu_pdf_urls,
    fetch_month_pages,
    parse_special_events_pdf,
    strip_portions,
)

# Menus stored before this kept the faded previous-month cells at the top of
# the calendar grid (October's held Sept 28-30) and "No meal listed" days;
# a menu stored before then is re-parsed in place on its next scan.
_REPARSE_BEFORE = datetime(2026, 10, 5, 3, 47, tzinfo=timezone.utc)
_NO_MEAL_RE = re.compile(r"^\s*(no (meal|lunch|menu)( listed| served)?|none|n/?a|tbd)\.?\s*$", re.IGNORECASE)


def menu_days_for_month(days: list[dict], year: int, month: int) -> list[dict]:
    """Only that month's days with a real meal: a calendar grid shows the
    neighbouring months' dates in its first/last rows, which the model reads
    as entries, and an empty cell can come back as 'No meal listed'."""
    return [
        d for d in days
        if d["date"].astimezone(ZoneInfo("America/New_York")).date().replace(day=1) == datetime(year, month, 1).date()
        and not _NO_MEAL_RE.match(d["description"] or "")
    ]


@register_job(
    kind="special_events.scan",
    default_name="Special events calendar scan",
    default_cron="0 8 * * 1",  # weekly - a themed monthly calendar, not something that changes daily
    description="Discovers and parses a school's own monthly 'special events' calendar PDF (spirit days, its own closures) and its monthly lunch menu PDF.",
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

    today = datetime.now(ZoneInfo("America/New_York")).date()
    pages = await fetch_month_pages(school.special_events_calendar_url, today)
    discovered = calendar_pdfs_from_pages(pages)
    menu_summary, menu_warning = await _scan_menus(db, school, pages, today)
    if not discovered:
        return f"WARNING[no_calendar_found]: no special-events calendar PDF found for this month or next; {menu_summary}"

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
        summary = f"found {len(discovered)} calendar(s), all already processed; {menu_summary}"
    else:
        summary = f"found {len(discovered)} calendar(s), parsed {new_pdfs} new, extracted {created} item(s); {menu_summary}"
    return f"WARNING[{menu_warning}]: {summary}" if menu_warning else summary


async def _scan_menus(db: AsyncSession, school: School, pages: list, today) -> tuple[str, str | None]:
    """Stores this month's and next month's lunch menu PDFs as the school's
    own LunchMenu (same shape as presence_menu.scan). Returns (summary,
    warning code or None). Oldest month first, so the newest menu ends up
    with the latest parsed_at - which is the one resolve_lunch_menu serves."""
    menus = await discover_menu_pdf_urls(pages, today)
    warning = None
    if not any((y, m) == (today.year, today.month) for y, m, _ in menus):
        stored_this_month = (
            await db.execute(
                select(LunchMenu.id).where(
                    LunchMenu.school_id == school.id,
                    LunchMenu.meal_type == "lunch",
                    LunchMenu.period_label == f"{_MONTH_NAMES[today.month - 1]} {today.year}",
                )
            )
        ).first()
        if not stored_this_month:
            warning = "no_menu_found"
    new_menus = 0
    for year, month, url in menus:
        stored = (
            await db.execute(select(LunchMenu).where(LunchMenu.school_id == school.id, LunchMenu.meal_type == "lunch", LunchMenu.source_pdf_url == url))
        ).scalar_one_or_none()
        if stored and stored.parsed_at >= _REPARSE_BEFORE:
            continue
        label = f"{_MONTH_NAMES[month - 1]} {year}"
        days = menu_days_for_month(await parse_menu_pdf(url, label, "lunch"), year, month)
        if not days:
            record_parse_issue("special_events.scan", "menu_parse_empty", url=url[:200])
            return f"nothing parsed from the {label} lunch menu", "menu_parse_empty"
        if stored:
            menu = stored
            await db.execute(delete(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu.id))
        else:
            menu = LunchMenu(school_id=school.id, meal_type="lunch", period_label=label, source_pdf_url=url)
            db.add(menu)
        await db.flush()
        menu.parsed_at = datetime.now(timezone.utc)
        for day in days:
            db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=day["date"], description=strip_portions(day["description"]), notes=day.get("notes")))
        new_menus += 1
    summary = f"found {len(menus)} lunch menu(s), {new_menus} newly parsed"
    if warning:
        summary += f" (no {_MONTH_NAMES[today.month - 1]} menu posted yet)"
    return summary, warning
