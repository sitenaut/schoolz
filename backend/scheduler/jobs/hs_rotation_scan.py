import re
from datetime import datetime, time
from urllib.parse import urlparse
from zoneinfo import ZoneInfo

import httpx
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scraper_client
from models import District, School, SchoolContentItem
from scheduler.errors import record_parse_issue
from scheduler.registry import register_job
from services import school_documents
from services.cycle_calendar import parse_cycle_pdf
from services.hs_rotation import BLOCKS_PREFIX, find_pdf_link, parse_rotation_pdf

_TZ = ZoneInfo("America/New_York")
_SOURCE = "rotation_pdf"
_TYPES = ["high"]


def pick_cycle_pdf(docs: list[dict]) -> str | None:
    """Newest-year `N day cycle` PDF among discovered documents."""
    found = [
        d for d in docs
        if d["doc_type"] == "letter_day_schedule"
        and urlparse(d["url"]).path.lower().endswith(".pdf")
        and re.search(r"cycle", d["title"] + " " + d["url"], re.I)
    ]
    found.sort(key=lambda d: d.get("academic_year") or "", reverse=True)
    return found[0]["url"] if found else None


async def _fetch_cycle_pdf(district: District) -> tuple[str, dict]:
    """What the district site links right now wins, so next year's PDF is picked
    up even though last year's stays online and would never 404. The configured
    URL is only the fallback for when the site can't be read."""
    url = district.hs_rotation_url
    if district.website_url:
        try:
            url = pick_cycle_pdf(await school_documents.discover_from_website(district.website_url)) or url
        except Exception:
            record_parse_issue("hs_rotation.scan", "unexpected_format", sample="district site discovery failed; using configured PDF")
    async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
        resp = await client.get(url)
        resp.raise_for_status()
    return url, parse_cycle_pdf(resp.content)


@register_job(
    kind="hs_rotation.scan",
    default_name="Day rotation scan",
    default_cron="0 */12 * * *",  # the sheet is marked "tentative - update as needed"
    description="Parses the district's day-rotation PDF into per-day 'Day N' items (Cherry Hill's shared high-school sheet, or a direct N-day cycle calendar PDF).",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none() if district_id else None
    if not district:
        return f"district {district_id} no longer exists"
    if not district.hs_rotation_url:
        return "district has no hs_rotation_url configured"

    wanted: dict[str, dict] = {}
    types = _TYPES
    if urlparse(district.hs_rotation_url).path.lower().endswith(".pdf"):
        # A bare N-day cycle calendar (Medford Lakes) rather than Cherry Hill's
        # page-that-links-a-sheet; it serves the district's non-high schools too.
        pdf_url, parsed = await _fetch_cycle_pdf(district)
        if not parsed["days"]:
            return f"WARNING[rotation_pdf_empty]: PDF at {pdf_url} parsed to zero days"
        types = sorted(
            set((await db.execute(select(School.school_type).where(School.district_id == district.id))).scalars())
        ) or _TYPES
        for day in parsed["days"]:
            if day["day_number"] is None:
                continue  # closures belong to the district calendar feed
            d = datetime.fromisoformat(day["date"]).date()
            wanted[f"hs_rotation:{d.isoformat()}"] = {
                "title": f"Day {day['day_number']}",
                "description": None,
                "start_date": datetime.combine(d, time.min, _TZ),
                "link_url": pdf_url,
            }
    else:

        page = await scraper_client.fetch_html(
            district.hs_rotation_url, wait_for_selector="#fsPageContent", block_assets=True
        )

        pdf_url = find_pdf_link(page["html"], district.hs_rotation_url)
        if not pdf_url:
            return "WARNING[no_rotation_pdf_link]: no PDF link found on the day-schedule page"

        async with httpx.AsyncClient(timeout=30, follow_redirects=True) as client:
            resp = await client.get(pdf_url)
            resp.raise_for_status()
        parsed = parse_rotation_pdf(resp.content)
        if not parsed["days"]:
            return f"WARNING[rotation_pdf_empty]: PDF at {pdf_url} parsed to zero days"

        for day in parsed["days"]:
            d = datetime.fromisoformat(day["date"]).date()
            start = datetime.combine(d, time.min, _TZ)
            if day["day_number"]:
                blocks = parsed["blocks"].get(day["day_number"])
                desc_parts = []
                if blocks:
                    desc_parts.append(BLOCKS_PREFIX + ", ".join(blocks))
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
            row.applies_to_school_types = types
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
                    applies_to_school_types=types,
                    **fields,
                )
            )
            created += 1
    for row in existing.values():
        await db.delete(row)
        removed += 1

    return f"hs rotation ({parsed['academic_year']}): {created} new, {updated} updated, {removed} removed, {len(parsed['days'])} days in PDF"
