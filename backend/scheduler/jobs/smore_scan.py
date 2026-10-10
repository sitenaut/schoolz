import uuid
from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.ext.asyncio import AsyncSession

from models import SmoreBlock, SmoreNewsletter
from scheduler.errors import parse_warning
from scheduler.registry import register_job
from services.content_extractor import extract_from_newsletter
from services.smore_parser import discover_current_issue_url, fetch_and_parse


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

    scan_url = newsletter.url
    if newsletter.source_type == "smore_archive":
        # newsletter.url is the school's own "newsletter archive" page,
        # not an issue - resolve it to whichever issue is current *this*
        # scan, since that's exactly the part that changes week to week.
        scan_url = await discover_current_issue_url(newsletter.url)
        if not scan_url:
            newsletter.last_scanned_at = datetime.now(timezone.utc)
            return f"WARNING[smore_archive_no_issues]: no dated Smore issue links found on {newsletter.url}"

    blocks = await fetch_and_parse(scan_url)

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
        return f"WARNING[smore_no_blocks]: fetched 0 blocks from {scan_url} - link may be dead or expired"

    existing_hashes = {
        row[0]
        for row in (
            await db.execute(select(SmoreBlock.content_hash).where(SmoreBlock.newsletter_id == newsletter.id))
        ).all()
    }

    # ON CONFLICT DO NOTHING: select_unseen_blocks covers what we already
    # stored, but a concurrent run of this same scan can insert the same
    # hashes between that read and this write. Losing that race must not fail
    # the scan - and only rows this run actually inserted go on to extraction,
    # so the winner alone extracts them.
    unseen = select_unseen_blocks(blocks, existing_hashes)
    new_blocks: list[SmoreBlock] = []
    if unseen:
        inserted_ids = (
            await db.execute(
                pg_insert(SmoreBlock)
                .values(
                    [
                        {
                            "id": str(uuid.uuid4()),
                            "newsletter_id": newsletter.id,
                            "position": block["position"],
                            "block_type": block["block_type"],
                            "text_content": block["text_content"],
                            "image_url": block["image_url"],
                            "link_url": block["link_url"],
                            "content_hash": block["content_hash"],
                            "pending_vision_extraction": block["block_type"] == "image",
                            "first_seen_at": datetime.now(timezone.utc),
                        }
                        for block in unseen
                    ]
                )
                .on_conflict_do_nothing(constraint="uq_smore_block_newsletter_hash")
                .returning(SmoreBlock.id)
            )
        ).scalars().all()
        if inserted_ids:
            new_blocks = list(
                (
                    await db.execute(
                        select(SmoreBlock).where(SmoreBlock.id.in_(inserted_ids)).order_by(SmoreBlock.position)
                    )
                ).scalars()
            )

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
