from datetime import datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, LunchMenu, LunchMenuItem, School
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.schoolcafe import SchoolCafeClient, match_school

_DAYS_AHEAD = 21
_SOURCE_PREFIX = "https://www.schoolcafe.com/"
_TZ = ZoneInfo("America/New_York")


@register_job(
    kind="schoolcafe_menu.scan",
    default_name="SchoolCafé menu scan",
    default_cron="0 */12 * * *",
    description="Pulls each school's breakfast/lunch menu for the next three weeks from a district's SchoolCafé site.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    if not district_id:
        return "no district_id in params - nothing to do"
    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        return f"district {district_id} no longer exists"
    if not district.schoolcafe_shortname:
        return "district has no schoolcafe_shortname configured"

    schools = (await db.execute(select(School).where(School.district_id == district.id))).scalars().all()
    source_url = f"{_SOURCE_PREFIX}{district.schoolcafe_shortname}/menus"
    today = datetime.now(_TZ).date()
    days = [today + timedelta(days=i) for i in range(_DAYS_AHEAD) if (today + timedelta(days=i)).weekday() < 5]

    matched = days_with_menu = 0
    unmatched: list[str] = []
    async with httpx.AsyncClient(timeout=30) as http:
        cafe = SchoolCafeClient(http)
        cafe_district = await cafe.district_id(district.schoolcafe_shortname)
        if not cafe_district:
            return f"WARNING[schoolcafe_unknown_district]: SchoolCafé has no district '{district.schoolcafe_shortname}'"
        cafe_schools = await cafe.schools(cafe_district)

        for school in schools:
            cafe_school = match_school(school.name, cafe_schools)
            if not cafe_school:
                unmatched.append(school.name)
                record_parse_issue("schoolcafe_menu.scan", "school_not_matched", school=school.name)
                continue
            matched += 1

            by_meal: dict[str, dict] = {}
            for day in days:
                for meal, description in (await cafe.day(cafe_school["SchoolId"], day, school.school_type)).items():
                    by_meal.setdefault(meal, {})[day] = description

            for meal, per_day in by_meal.items():
                menu = (
                    await db.execute(
                        select(LunchMenu).where(
                            LunchMenu.school_id == school.id, LunchMenu.meal_type == meal, LunchMenu.source_pdf_url == source_url
                        )
                    )
                ).scalar_one_or_none()
                if not menu:
                    menu = LunchMenu(school_id=school.id, meal_type=meal, period_label="SchoolCafé", source_pdf_url=source_url)
                    db.add(menu)
                    await db.flush()
                menu.parsed_at = datetime.now(timezone.utc)
                # Rolling window: the fetched days are replaced wholesale,
                # so a menu change on SchoolCafé shows up on the next run.
                window_start = datetime.combine(days[0], time(0), _TZ)
                await db.execute(delete(LunchMenuItem).where(LunchMenuItem.lunch_menu_id == menu.id, LunchMenuItem.menu_date >= window_start))
                for day, description in per_day.items():
                    db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=datetime.combine(day, time(12), _TZ), description=description))
                    days_with_menu += 1

    summary = f"{matched}/{len(schools)} school(s) matched on SchoolCafé, {days_with_menu} school-day menu(s) stored"
    if unmatched:
        return f"WARNING[schoolcafe_school_unmatched]: {summary}; no SchoolCafé match for: {', '.join(unmatched)}"
    if matched and not days_with_menu:
        return f"WARNING[schoolcafe_no_menus]: {summary}"
    return summary
