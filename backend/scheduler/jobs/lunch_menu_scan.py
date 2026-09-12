from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, LunchMenu, LunchMenuItem
from scheduler.registry import register_job
from services.lunch_menu import discover_current_menus, parse_menu_pdf


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

    discovered = await discover_current_menus(district.food_services_menu_url)
    if not discovered:
        return "WARNING[no_menu_pdfs]: no menu PDFs found on the food-services page"
    new_menus = 0
    for entry in discovered:
        existing = await db.execute(
            select(LunchMenu).where(
                LunchMenu.district_id == district.id,
                LunchMenu.school_type == entry["school_type"],
                LunchMenu.meal_type == entry["meal_type"],
                LunchMenu.source_pdf_url == entry["pdf_url"],
            )
        )
        if existing.scalar_one_or_none():
            continue  # already parsed this exact PDF

        days = await parse_menu_pdf(entry["pdf_url"], entry["period_label"])
        if not days:
            continue

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

    return f"found {len(discovered)} menu(s), {new_menus} newly parsed"
