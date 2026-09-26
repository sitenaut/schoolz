from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SmoreBlock, SmoreNewsletter
from scheduler.errors import parse_warning
from scheduler.registry import register_job
from services.content_extractor import extract_from_newsletter
from services.smore_parser import fetch_and_parse


def select_unseen_blocks(blocks: list[dict], existing_hashes: set[str]) -> list[dict]:
    """Blocks worth storing: those whose content we haven't seen before.

    Skips two kinds of duplicate, and the second one is the reason this is
    a function rather than an inline check:

    1. Content already stored from an earlier scan. Smore pages get edited
       in place week to week, so most blocks on any given run are ones we
       already have.
    2. Content repeated *within this same parse*. A newsletter can include
       the same block twice (Beck's 9-11 issue does), and since
       content_hash is unique per (newsletter, hash), queueing both makes
       the flush fail with a UniqueViolationError that takes down the
       entire scan - every other block included. Two identical blocks are
       the same content by definition, so keeping the first is correct.

    Pure on purpose: the bug in (2) reached production because the only way
    to exercise this logic was through the database and a live parse.
    """
    seen = set(existing_hashes)
    unseen = []
    for block in blocks:
        if block["content_hash"] in seen:
            continue
        seen.add(block["content_hash"])
        unseen.append(block)
    return unseen


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

    if not blocks:
        # A real newsletter always has at least one block - a Smore link
        # that has expired (confirmed real: several Cherry Hill schools'
        # "stable" URLs went stale mid-week while still reporting success)
        # renders a different page entirely, with no .block-wrapper
        # elements, rather than 404ing or timing out. That made an expired
        # link indistinguishable from "no new content this week" - both
        # produced status=success with nothing for anyone to notice. Zero
        # blocks total (not just zero new ones) is the honest signal that
        # the URL itself needs attention, not the newsletter's content.
        newsletter.last_scanned_at = datetime.now(timezone.utc)
        return f"WARNING[smore_no_blocks]: fetched 0 blocks from {newsletter.url} - link may be dead or expired"

    existing_hashes = {
        row[0]
        for row in (
            await db.execute(select(SmoreBlock.content_hash).where(SmoreBlock.newsletter_id == newsletter.id))
        ).all()
    }

    new_blocks: list[SmoreBlock] = []
    for block in select_unseen_blocks(blocks, existing_hashes):
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
