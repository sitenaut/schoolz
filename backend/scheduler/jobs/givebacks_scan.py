from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import GivebacksBlock, School
from scheduler.errors import parse_warning
from scheduler.registry import register_job
from scheduler.jobs.smore_scan import select_unseen_blocks
from services.givebacks import fetch_and_parse
from services.givebacks_extractor import extract_from_pta_page


@register_job(
    kind="givebacks.scan",
    default_name="Givebacks PTA page scan",
    default_cron="0 9 * * 1",  # Monday mornings, same cadence as Smore
    description="Crawls a PTA's Givebacks site and stores any content blocks not seen before.",
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"
    if not school.givebacks_shortname:
        return f"WARNING[givebacks_no_shortname]: school {school.name} has no givebacks_shortname set"

    blocks = await fetch_and_parse(school.givebacks_shortname)
    if not blocks:
        # Same reasoning as smore_scan.py's empty-blocks warning: an org
        # shortname that's stopped resolving (renamed, deleted) looks
        # identical to "no new content this week" unless zero blocks is
        # treated as its own signal.
        return f"WARNING[givebacks_no_blocks]: fetched 0 blocks for shortname '{school.givebacks_shortname}' - org may no longer exist"

    existing_hashes = {
        row[0]
        for row in (
            await db.execute(
                select(GivebacksBlock.content_hash).where(GivebacksBlock.school_id == school.id)
            )
        ).all()
    }

    new_blocks: list[GivebacksBlock] = []
    image_bytes_by_block_id: dict[str, bytes] = {}
    for block in select_unseen_blocks(blocks, existing_hashes):
        row = GivebacksBlock(
            school_id=school.id,
            page_path=block["page_path"],
            position=block["position"],
            block_type=block["block_type"],
            text_content=block["text_content"],
            image_url=block["image_url"],
            link_url=block["link_url"],
            content_hash=block["content_hash"],
            pending_vision_extraction=(block["block_type"] == "image"),
        )
        db.add(row)
        new_blocks.append(row)
        if block.get("_image_bytes"):
            # Keyed after flush (once the row has a real id) - see below.
            row._pending_image_bytes = block["_image_bytes"]
    await db.flush()
    for row in new_blocks:
        pending = getattr(row, "_pending_image_bytes", None)
        if pending:
            image_bytes_by_block_id[row.id] = pending

    summary = f"fetched {len(blocks)} block(s), {len(new_blocks)} new"

    if new_blocks:
        extraction_note = await extract_from_pta_page(db, school, new_blocks, image_bytes_by_block_id)
        summary += f" · extraction: {extraction_note}"
        warning_code = parse_warning(extraction_note)
        if warning_code:
            summary = f"WARNING[{warning_code}]: " + summary

    return summary
