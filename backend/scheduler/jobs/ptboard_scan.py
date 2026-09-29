from datetime import datetime, timezone

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SmoreBlock, SmoreNewsletter
from scheduler.errors import parse_warning
from scheduler.registry import register_job
from services.content_extractor import extract_from_newsletter
from services.ptboard_parser import fetch_and_parse

_JOB_KIND = "ptboard.scan"


@register_job(
    kind=_JOB_KIND,
    default_name="PTBoard scan",
    default_cron="0 8 * * 1",  # Monday mornings, same cadence as Smore
    description="Fetches a PTBoard PTA site's home page and stores any feed items (forms, announcements, signups, campaigns) not seen before.",
    param_schema={"type": "object", "properties": {"newsletter_id": {"type": "string"}}, "required": ["newsletter_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    newsletter_id = params.get("newsletter_id")
    if not newsletter_id:
        return "no newsletter_id in params - nothing to do"

    newsletter = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.id == newsletter_id))).scalar_one_or_none()
    if not newsletter:
        return f"newsletter {newsletter_id} no longer exists"

    items = await fetch_and_parse(newsletter.url)

    # Unlike Smore, a PTA with genuinely nothing currently posted (no open
    # forms, no announcements) is a real, unremarkable state - not treated
    # as a dead-link signal the way smore_scan.py's "0 blocks" is.
    if not items:
        newsletter.last_scanned_at = datetime.now(timezone.utc)
        return "fetched 0 feed items - nothing currently posted"

    existing_hashes = {
        row[0] for row in (await db.execute(select(SmoreBlock.content_hash).where(SmoreBlock.newsletter_id == newsletter.id))).all()
    }

    new_blocks: list[SmoreBlock] = []
    seen_this_run: set[str] = set()
    for item in items:
        if item["content_hash"] in existing_hashes or item["content_hash"] in seen_this_run:
            continue
        seen_this_run.add(item["content_hash"])
        row = SmoreBlock(
            newsletter_id=newsletter.id,
            position=item["position"],
            block_type=item["block_type"],
            text_content=item["text_content"],
            image_url=item["image_url"],
            link_url=item["link_url"],
            content_hash=item["content_hash"],
            pending_vision_extraction=False,
        )
        db.add(row)
        new_blocks.append(row)
    await db.flush()

    newsletter.last_scanned_at = datetime.now(timezone.utc)
    summary = f"fetched {len(items)} feed item(s), {len(new_blocks)} new"

    if new_blocks:
        extraction_note = await extract_from_newsletter(db, newsletter, new_blocks, job_kind=_JOB_KIND)
        summary += f" · extraction: {extraction_note}"
        warning_code = parse_warning(extraction_note)
        if warning_code:
            summary = f"WARNING[{warning_code}]: " + summary

    return summary
