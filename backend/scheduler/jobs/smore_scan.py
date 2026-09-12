from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SmoreBlock, SmoreNewsletter
from scheduler.errors import parse_warning
from scheduler.registry import register_job
from services.content_extractor import extract_from_newsletter
from services.smore_parser import fetch_and_parse


@register_job(
    kind="smore.scan",
    default_name="Smore newsletter scan",
    default_cron="0 8 * * 1",  # Monday mornings - most of these are weekly
    description="Fetches a Smore (or similar) newsletter URL and stores any content blocks not seen before.",
    param_schema={"type": "object", "properties": {"newsletter_id": {"type": "string"}}, "required": ["newsletter_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    newsletter_id = params.get("newsletter_id")
    if not newsletter_id:
        return "no newsletter_id in params - nothing to do"

    newsletter = (
        await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.id == newsletter_id))
    ).scalar_one_or_none()
    if not newsletter:
        return f"newsletter {newsletter_id} no longer exists"

    blocks = await fetch_and_parse(newsletter.url)

    existing_hashes = {
        row[0]
        for row in (
            await db.execute(select(SmoreBlock.content_hash).where(SmoreBlock.newsletter_id == newsletter.id))
        ).all()
    }

    new_blocks: list[SmoreBlock] = []
    for block in blocks:
        # Checked against hashes seen *in this batch* as well as ones
        # already stored: a single newsletter can legitimately repeat a
        # block (Beck's 9-11 issue repeats one), and since content_hash is
        # unique per (newsletter, hash), queueing both fails the whole
        # scan on flush with a UniqueViolationError - which is exactly
        # what took Beck's newsletter down. Two identical blocks are the
        # same content by definition, so keeping the first is correct.
        if block["content_hash"] in existing_hashes:
            continue
        existing_hashes.add(block["content_hash"])
        row = SmoreBlock(
            newsletter_id=newsletter.id,
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
    await db.flush()

    newsletter.last_scanned_at = datetime.now(timezone.utc)
    summary = f"fetched {len(blocks)} block(s), {len(new_blocks)} new"

    if new_blocks:
        extraction_note = await extract_from_newsletter(db, newsletter, new_blocks)
        summary += f" · extraction: {extraction_note}"
        # The runner only reads the prefix of the handler's own return value
        # - propagate whichever code extract_from_newsletter's own warning
        # carried (image_unsupported / llm_max_tokens) rather than a generic
        # re-wrap, so it groups correctly in Grafana.
        warning_code = parse_warning(extraction_note)
        if warning_code:
            summary = f"WARNING[{warning_code}]: " + summary

    return summary
