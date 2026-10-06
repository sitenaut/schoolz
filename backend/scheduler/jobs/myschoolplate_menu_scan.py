from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LunchMenu, LunchMenuItem, School
from scheduler.registry import register_job
from services.fdmealplanner import day_descriptions
from services.myschoolplate import fetch_config, fetch_meal_periods, fetch_month_entrees, location_page_url, parse_location

_DAYS_AHEAD = 21
_TZ = ZoneInfo("America/New_York")


def _months(start: date, end: date) -> list[date]:
    out, cur = [], start.replace(day=1)
    while cur <= end:
        out.append(max(cur, start))
        cur = (cur + timedelta(days=32)).replace(day=1)
    return out


@register_job(
    kind="myschoolplate_menu.scan",
    default_name="MySchoolPlate menu scan",
    default_cron="0 */12 * * *",
    description="Pulls a school's breakfast/lunch entrées for the next three weeks from Aramark MySchoolPlate (<tenant>.myschoolplate.com).",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"
    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    location = parse_location(school.myschoolplate_location or "")
    if not location:
        return f"WARNING[myschoolplate_bad_location]: expected tenant/location-key, got {school.myschoolplate_location!r}"
    tenant, key = location

    today = datetime.now(_TZ).date()
    end = today + timedelta(days=_DAYS_AHEAD)
    stored: dict[str, int] = {}
    async with httpx.AsyncClient(timeout=60) as http:
        cfg = await fetch_config(http, tenant)
        if not cfg:
            return f"WARNING[myschoolplate_no_config]: {tenant}.myschoolplate.com's page carries no menu API config"
        periods = await fetch_meal_periods(http, cfg)
        for meal, period_id in periods.items():
            by_day: dict[date, list[str]] = {}
            for month_day in _months(today, end):
                for day, items in (await fetch_month_entrees(http, cfg, key, period_id, month_day)).items():
                    if today <= day <= end:
                        by_day[day] = items
            descriptions = day_descriptions(by_day)
            if not descriptions:
                continue
            source_url = location_page_url(tenant, key)
            menu = (
                await db.execute(
                    select(LunchMenu).where(LunchMenu.school_id == school.id, LunchMenu.meal_type == meal, LunchMenu.source_pdf_url == source_url)
                )
            ).scalar_one_or_none()
            if not menu:
                menu = LunchMenu(school_id=school.id, meal_type=meal, period_label="MySchoolPlate", source_pdf_url=source_url)
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
        return f"WARNING[myschoolplate_no_menus]: no menu days in the next {_DAYS_AHEAD} days for {school.myschoolplate_location}"
    return ", ".join(f"{meal}: {n} day(s)" for meal, n in stored.items())
