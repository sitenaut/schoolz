from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, SchoolContentItem
from scheduler.registry import register_job
from services import district_calendar_pdf as svc


@register_job(
    kind="district_calendar_pdf.scan",
    default_name="District calendar PDF scan",
    default_cron="0 */12 * * *",
    description="Finds the school-year calendar PDF on a district page and turns its dated entries into district-wide calendar items.",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none() if district_id else None
    if not district:
        return f"district {district_id} no longer exists"
    if not district.calendar_pdf_url:
        return "district has no calendar_pdf_url configured"

    fetched = await svc.fetch_pdf(district.calendar_pdf_url)
    if not fetched:
        return "WARNING[no_calendar_pdf_link]: no PDF link found on the calendar page"
    pdf_url, data = fetched
    digest = svc.content_hash(data)

    existing = {
        row.external_uid: row
        for row in (
            await db.execute(
                select(SchoolContentItem).where(SchoolContentItem.district_id == district.id, SchoolContentItem.source == svc.SOURCE)
            )
        ).scalars()
    }
    # The uid carries the file's content hash, so unchanged bytes mean the
    # rows are already right - skip the model call every 12h.
    if any(uid.startswith(f"{svc.UID_PREFIX}:{digest}:") for uid in existing):
        return f"calendar PDF unchanged ({digest}), {len(existing)} items on file"

    events = await svc.extract_events(data)
    wanted, skipped = svc.build_items(events, pdf_url, digest)
    if not wanted:
        return f"WARNING[calendar_pdf_empty]: {pdf_url} produced no calendar entries"

    created = removed = 0
    for uid, fields in wanted.items():
        if uid in existing:
            existing.pop(uid)
            continue
        db.add(
            SchoolContentItem(
                scope="district",
                district_id=district.id,
                category="event",
                is_all_day=True,
                source=svc.SOURCE,
                external_uid=uid,
                **fields,
            )
        )
        created += 1
    # A revised PDF replaces the old one wholesale.
    for row in existing.values():
        await db.delete(row)
        removed += 1

    note = f", {skipped} skipped (bad date)" if skipped else ""
    return f"district calendar ({digest}): {created} new, {removed} removed, {len(wanted)} entries in PDF{note}"
