from datetime import datetime, timezone
from zoneinfo import ZoneInfo

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LunchMenu, LunchMenuItem, School
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.lunch_menu import parse_menu_pdf, pick_presence_menus
from services.presence_documents import list_page_documents


@register_job(
    kind="presence_menu.scan",
    default_name="Presence menu scan",
    default_cron="0 */12 * * *",
    description="Reads a school's breakfast/lunch menu files (PDF or picture) from a Presence site's documents widget.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"
    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.presence_menu_page_url:
        return "school has no presence_menu_page_url configured"

    documents = await list_page_documents(school.presence_menu_page_url)
    if not documents:
        return "WARNING[presence_no_documents]: the page has no documents widget (or isn't a Presence site)"
    picked = pick_presence_menus(documents, datetime.now(ZoneInfo("America/New_York")).date())
    if not picked:
        return f"WARNING[no_menu_files]: none of the {len(documents)} documents is a current or upcoming monthly menu"

    new_menus = 0
    empty: list[str] = []
    for entry in picked:  # oldest month first, so the newest ends up with the latest parsed_at
        stored = (
            await db.execute(
                select(LunchMenu).where(LunchMenu.school_id == school.id, LunchMenu.meal_type == entry["meal_type"], LunchMenu.source_pdf_url == entry["url"])
            )
        ).scalar_one_or_none()
        if stored:
            continue
        days = await parse_menu_pdf(entry["url"], entry["period_label"].replace(" (Pre-K)", ""), entry["meal_type"])
        if not days:
            record_parse_issue("presence_menu.scan", "menu_parse_empty", url=entry["url"][:200])
            empty.append(f"{entry['meal_type']} {entry['period_label']}")
            continue
        menu = LunchMenu(school_id=school.id, meal_type=entry["meal_type"], period_label=entry["period_label"], source_pdf_url=entry["url"])
        db.add(menu)
        await db.flush()
        menu.parsed_at = datetime.now(timezone.utc)
        for day in days:
            db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=day["date"], description=day["description"], notes=day.get("notes")))
        new_menus += 1

    summary = f"found {len(picked)} menu file(s), {new_menus} newly parsed"
    if empty:
        return f"WARNING[menu_parse_empty]: {summary}; nothing parsed from: {', '.join(empty)}"
    return summary
