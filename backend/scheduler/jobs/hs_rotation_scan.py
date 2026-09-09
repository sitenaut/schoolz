from datetime import datetime, time
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scraper_client
from models import District, SchoolContentItem
from scheduler.registry import register_job
from services.hs_rotation import find_pdf_link, parse_rotation_pdf

_TZ = ZoneInfo("America/New_York")
_SOURCE = "rotation_pdf"
_TYPES = ["high"]


@register_job(
    kind="hs_rotation.scan",
    default_name="High school day rotation scan",
    default_cron="0 */12 * * *",  # the sheet is marked "tentative - update as needed"
    description="Parses the district's shared East/West day-rotation PDF into per-day 'Day N' items for high schools.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none() if district_id else None
    if not district:
        return f"district {district_id} no longer exists"
    if not district.hs_rotation_url:
        return "district has no hs_rotation_url configured"

    page = await scraper_client.fetch_html(district.hs_rotation_url, wait_for_selector="#fsPageContent")
    pdf_url = find_pdf_link(page["html"], district.hs_rotation_url)
    if not pdf_url:
        return "WARNING: no PDF link found on the day-schedule page"

    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(pdf_url)
        resp.raise_for_status()
    parsed = parse_rotation_pdf(resp.content)
    if not parsed["days"]:
        return f"WARNING: PDF at {pdf_url} parsed to zero days"

    wanted: dict[str, dict] = {}
    for day in parsed["days"]:
        d = datetime.fromisoformat(day["date"]).date()
        start = datetime.combine(d, time.min, _TZ)
        if day["day_number"]:
            blocks = parsed["blocks"].get(day["day_number"])
            desc_parts = []
            if blocks:
                desc_parts.append("Blocks " + ", ".join(blocks))
            if day["cycle"]:
                desc_parts.append(f"Cycle {day['cycle']}")
            wanted[f"hs_rotation:{d.isoformat()}"] = {
                "title": f"Day {day['day_number']}",
                "description": " · ".join(desc_parts) or None,
                "start_date": start,
                "link_url": pdf_url,
            }
        if day["early_dismissal"]:
            # The district ICS feed carries district-wide early dismissals;
            # this catches the high-school-only ones (PSAT day, finals).
            wanted[f"hs_rotation:{d.isoformat()}:early"] = {
                "title": "Early Dismissal",
                "description": day["note"],
                "start_date": start,
                "link_url": pdf_url,
            }

    existing = {
        row.external_uid: row
        for row in (
            await db.execute(
                select(SchoolContentItem).where(SchoolContentItem.district_id == district.id, SchoolContentItem.source == _SOURCE)
            )
        ).scalars()
    }
    # Same-day early dismissal already known from the district feed - don't double it.
    feed_early_dates = {
        row.start_date.astimezone(_TZ).date()
        for row in (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.district_id == district.id,
                    SchoolContentItem.source == "ics_feed",
                    SchoolContentItem.title.ilike("%early dismissal%"),
                )
            )
        ).scalars()
    }

    created = updated = removed = 0
    for uid, fields in wanted.items():
        if uid.endswith(":early") and fields["start_date"].date() in feed_early_dates:
            continue
        row = existing.pop(uid, None)
        if row:
            for k, v in fields.items():
                setattr(row, k, v)
            row.is_current = True
            updated += 1
        else:
            db.add(
                SchoolContentItem(
                    scope="district",
                    district_id=district.id,
                    category="event",
                    is_all_day=True,
                    source=_SOURCE,
                    external_uid=uid,
                    applies_to_school_types=_TYPES,
                    **fields,
                )
            )
            created += 1
    for row in existing.values():
        await db.delete(row)
        removed += 1

    return f"hs rotation ({parsed['academic_year']}): {created} new, {updated} updated, {removed} removed, {len(parsed['days'])} days in PDF"
