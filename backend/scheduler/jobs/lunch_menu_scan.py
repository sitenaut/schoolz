from datetime import datetime, timezone

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, LunchMenu, LunchMenuItem, School
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.lunch_menu import discover_current_menus, parse_menu_pdf


# Menus stored before this had their partial first week dropped by the parser
# (Cherry Hill's October menu lost Oct 1-2); there is no admin path to delete a
# stored menu, so one older than this is re-parsed in place on its next scan.
_REPARSE_BEFORE = datetime(2026, 10, 1, 5, 30, tzinfo=timezone.utc)


@register_job(
    kind="lunch_menu.scan",
    default_name="Lunch/breakfast menu scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh like the other non-Smore scans
    description="Discovers and parses a district's current breakfast/lunch menu PDFs, per school type.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    if not district_id:
        return "no district_id in params - nothing to do"

    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        return f"district {district_id} no longer exists"
    if not district.food_services_menu_url:
        return "district has no food_services_menu_url configured"

    school_types = set(
        (await db.execute(select(School.school_type).where(School.district_id == district.id).distinct())).scalars().all()
    )
    discovered = await discover_current_menus(district.food_services_menu_url, school_types=sorted(t for t in school_types if t))
    if not discovered:
        return "WARNING[no_menu_pdfs]: no menu PDFs found on the food-services page"
    new_menus = 0
    empty: list[str] = []
    parsed_days: dict[str, list[dict]] = {}  # one PDF can serve several school types
    for entry in discovered:
        existing = await db.execute(
            select(LunchMenu).where(
                LunchMenu.district_id == district.id,
                LunchMenu.school_type == entry["school_type"],
                LunchMenu.meal_type == entry["meal_type"],
                LunchMenu.source_pdf_url == entry["pdf_url"],
            )
        )
        stored = existing.scalar_one_or_none()
        if stored and stored.parsed_at >= _REPARSE_BEFORE:
            continue  # already parsed this exact PDF

        if entry["pdf_url"] not in parsed_days:
            parsed_days[entry["pdf_url"]] = await parse_menu_pdf(entry["pdf_url"], entry["period_label"])
        days = parsed_days[entry["pdf_url"]]
        if not days:
            record_parse_issue("lunch_menu.scan", "menu_parse_empty", url=entry["pdf_url"][:200], school_type=entry["school_type"])
            empty.append(f"{entry['school_type']} {entry['meal_type']} {entry['period_label']}")
            continue

        if stored:
            menu = stored
            menu.parsed_at = datetime.now(timezone.utc)
            await db.execute(delete(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu.id))
        else:
            menu = LunchMenu(
                district_id=district.id,
                school_type=entry["school_type"],
                meal_type=entry["meal_type"],
                period_label=entry["period_label"],
                source_pdf_url=entry["pdf_url"],
            )
            db.add(menu)
        await db.flush()
        for day in days:
            db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=day["date"], description=day["description"], notes=day.get("notes")))
        new_menus += 1

    summary = f"found {len(discovered)} menu(s), {new_menus} newly parsed"
    if empty:
        # An empty parse used to be skipped silently, so a month that never got stored still read as success.
        return f"WARNING[menu_parse_empty]: {summary}; nothing parsed from: {', '.join(empty)}"
    return summary
