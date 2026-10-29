from collections import Counter
from datetime import UTC, datetime
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LunchMenu, LunchMenuItem, School
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services.lunch_menu import (
    list_apptegy_page_images,
    list_google_sites_menu_files,
    parse_menu_pdf,
    pick_presence_menus,
)
from services.presence_documents import list_page_documents

_MONTHS = ("January", "February", "March", "April", "May", "June", "July", "August", "September", "October", "November", "December")


@register_job(
    kind="presence_menu.scan",
    default_name="Presence menu scan",
    default_cron="0 */12 * * *",
    description="Reads a school's breakfast/lunch menu files (PDF or picture) from a Presence site's documents widget, a Google Site page of Drive files, or an Apptegy page of menu pictures.",
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

    google_site = urlparse(school.presence_menu_page_url).netloc == "sites.google.com"
    try:
        documents = await (list_google_sites_menu_files if google_site else list_page_documents)(school.presence_menu_page_url)
    except httpx.HTTPError:
        if google_site:
            raise
        documents = []  # an Apptegy site answers a plain GET with its challenge page
    if not documents and not google_site:
        documents = await list_apptegy_page_images(school.presence_menu_page_url)
    if not documents:
        return "WARNING[presence_no_documents]: the page has no documents widget or menu pictures (or isn't a Presence or Apptegy site)"
    today = datetime.now(ZoneInfo("America/New_York")).date()
    picked = pick_presence_menus(documents, today)
    if not picked:
        return f"WARNING[no_menu_files]: none of the {len(documents)} documents is a current or upcoming monthly menu"

    new_menus = standing = 0
    empty: list[str] = []
    for entry in picked:
        stored = (
            await db.execute(
                select(LunchMenu).where(LunchMenu.school_id == school.id, LunchMenu.meal_type == entry["meal_type"], LunchMenu.source_pdf_url == entry["url"])
            )
        ).scalar_one_or_none()
        if stored:
            continue
        days = await parse_menu_pdf(entry["url"], (entry["period_label"] or "").replace(" (Pre-K)", "") or None, entry["meal_type"])
        if not days and not entry["period_label"]:
            # A picture with no month in its title and no calendar in it is a standing
            # menu (Pitman's high school breakfast list), not a month that failed to read.
            standing += 1
            continue
        if not days:
            record_parse_issue("presence_menu.scan", "menu_parse_empty", url=entry["url"][:200])
            empty.append(f"{entry['meal_type']} {entry['period_label'] or 'undated'}")
            continue
        label = entry["period_label"]
        if not label:
            # A picture with no month in its title: the month is the one most of its days fall in.
            (year, month), _ = Counter((d["date"].year, d["date"].month) for d in days).most_common(1)[0]
            if (year, month) < (today.year, today.month):
                continue  # last month's picture, still up
            label = f"{_MONTHS[month - 1]} {year}"
        menu = LunchMenu(school_id=school.id, meal_type=entry["meal_type"], period_label=label, source_pdf_url=entry["url"])
        db.add(menu)
        await db.flush()
        menu.parsed_at = datetime.now(UTC)
        for day in days:
            db.add(LunchMenuItem(lunch_menu_id=menu.id, menu_date=day["date"], description=day["description"], notes=day.get("notes")))
        new_menus += 1

    summary = f"found {len(picked)} menu file(s), {new_menus} newly parsed" + (f", {standing} standing (no calendar)" if standing else "")
    if empty:
        return f"WARNING[menu_parse_empty]: {summary}; nothing parsed from: {', '.join(empty)}"
    return summary
