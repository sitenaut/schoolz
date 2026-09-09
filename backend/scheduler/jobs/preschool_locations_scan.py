import re

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

import scraper_client
from models import District, School, derive_school_short_name
from scheduler.registry import register_job
from services.preschool_locations import parse_preschool_locations


def _street_key(address: str | None) -> str | None:
    if not address:
        return None
    street = address.split(",")[0].strip().lower()
    return re.sub(r"[^a-z0-9 ]", "", street) or None


@register_job(
    kind="preschool_locations.scan",
    default_name="Preschool locations scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh
    description="Parses the district's preschool provider directory into School records (mostly private third-party sites).",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    if not district_id:
        return "no district_id in params - nothing to do"

    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        return f"district {district_id} no longer exists"
    if not district.preschool_locations_url:
        return "district has no preschool_locations_url configured"

    result = await scraper_client.fetch_html(district.preschool_locations_url, wait_for_selector="a")
    entries = parse_preschool_locations(result["html"])
    if not entries:
        return "WARNING: no preschool locations found - the page's structure may have changed"

    existing_schools = (await db.execute(select(School).where(School.district_id == district_id))).scalars().all()
    existing_by_street = {_street_key(s.address): s for s in existing_schools if s.address}
    existing_by_name = {s.name.strip().lower(): s for s in existing_schools}

    created = updated = skipped_existing = 0
    for entry in entries:
        street_key = _street_key(entry["address"])
        row = existing_by_street.get(street_key) or existing_by_name.get(entry["name"].strip().lower())
        if row:
            # Same physical building as an already-tracked School (e.g.
            # "Joyce Kilmer Preschool" == Joyce Kilmer Elementary) - don't
            # create a duplicate, just fill in anything missing.
            if not row.website_url and entry["website_url"]:
                row.website_url = entry["website_url"]
            skipped_existing += 1
            continue

        row = existing_by_name.get(entry["name"].strip().lower())
        if row:
            row.address = entry["address"] or row.address
            row.main_phone = entry["main_phone"] or row.main_phone
            row.website_url = entry["website_url"] or row.website_url
            updated += 1
            continue

        db.add(
            School(
                name=entry["name"],
                short_name=derive_school_short_name(entry["name"], district.name),
                district_id=district_id,
                school_type="other",
                address=entry["address"],
                main_phone=entry["main_phone"],
                website_url=entry["website_url"],
            )
        )
        created += 1

    return f"preschool locations: {created} new, {updated} updated, {skipped_existing} already tracked (same building), {len(entries)} total on page"
