from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LunchMenu, LunchMenuItem, School
from scheduler.registry import register_job
from services.fdmealplanner import day_descriptions
from services.healthepro import fetch_entrees, fetch_site_menus, menu_page_url, parse_location, pick_menus

_DAYS_AHEAD = 21
_TZ = ZoneInfo("America/New_York")


@register_job(
    kind="healthepro_menu.scan",
    default_name="Health-e Pro menu scan",
    default_cron="0 */12 * * *",
    description="Pulls a school's breakfast/lunch entrées for the next three weeks from Health-e Pro (menus.healthepro.com).",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"
    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    location = parse_location(school.healthepro_location or "")
    if not location:
        return f"WARNING[healthepro_bad_location]: expected org/site, got {school.healthepro_location!r}"
    org, site = location

    today = datetime.now(_TZ).date()
    end = today + timedelta(days=_DAYS_AHEAD)
    stored: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=30) as http:
        chosen = pick_menus(await fetch_site_menus(http, org, site))
        if not chosen:
            return f"WARNING[healthepro_no_menus]: site {school.healthepro_location} lists no breakfast or lunch menu"
        for meal, menu_info in chosen.items():
            descriptions = day_descriptions(await fetch_entrees(http, org, menu_info["id"], today, end))
            if not descriptions:
                continue
            source_url = menu_page_url(org, site)
            menu = (
                await db.execute(
                    select(LunchMenu).where(LunchMenu.school_id == school.id, LunchMenu.meal_type == meal, LunchMenu.source_pdf_url == source_url)
                )
            ).scalar_one_or_none()
            if not menu:
                menu = LunchMenu(school_id=school.id, meal_type=meal, period_label="Health-e Pro", source_pdf_url=source_url)
                db.add(menu)
                await db.flush()
            menu.parsed_at = datetime.now(timezone.utc)
            # Rolling window, replaced wholesale - a menu change upstream
            # shows up on the next run.
            await db.execute(
                delete(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu.id, LunchMenuItem.menu_date >= datetime.combine(today, time(0), _TZ))
            )
            for day, description in descriptions.items():
                db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=datetime.combine(day, time(12), _TZ), description=description))
            stored[meal] = len(descriptions)

    if not stored:
        return f"WARNING[healthepro_no_menus]: no menu days in the next {_DAYS_AHEAD} days for site {school.healthepro_location}"
    return ", ".join(f"{meal}: {n} day(s)" for meal, n in stored.items())
