from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SmoreBlock, SmoreNewsletter
from scheduler.errors import parse_warning
from scheduler.registry import register_job
from services.backpack_parser import discover_backpack_links, resolve_final_url, resource_content_hash
from services.content_extractor import extract_from_newsletter, pending_vision_retries

_JOB_KIND = "virtual_backpack.scan"


@register_job(
    kind=_JOB_KIND,
    default_name="Virtual backpack scan",
    default_cron="0 9 * * *",  # daily - a running bulletin board, not a weekly issue like Smore
    description="Discovers new flyer/event links on a district's running bulletin-board page and extracts them the same way a newsletter block is.",
    param_schema={"type": "object", "properties": {"newsletter_id": {"type": "string"}}, "required": ["newsletter_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    newsletter_id = params.get("newsletter_id")
    if not newsletter_id:
        return "no newsletter_id in params - nothing to do"

    newsletter = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.id == newsletter_id))).scalar_one_or_none()
    if not newsletter:
        return f"newsletter {newsletter_id} no longer exists"

    links = await discover_backpack_links(newsletter.url)
    if not links:
        newsletter.last_scanned_at = datetime.now(UTC)
        return "WARNING[backpack_no_links]: found 0 resource links on the page - it may have changed shape"

    existing_hashes = {
        row[0] for row in (await db.execute(select(SmoreBlock.content_hash).where(SmoreBlock.newsletter_id == newsletter.id))).all()
    }

    new_blocks: list[SmoreBlock] = []
    for position, link in enumerate(links):
        content_hash = resource_content_hash(link["resource_id"])
        if content_hash in existing_hashes:
            continue
        existing_hashes.add(content_hash)  # a page can repeat the same resource id in more than one section

        final_url = await resolve_final_url(link["wrapper_url"])
        if not final_url:
            continue

        row = SmoreBlock(
            newsletter_id=newsletter.id,
            position=position,
            block_type="link",
            text_content=link["title"],
            image_url=None,
            link_url=final_url,
            content_hash=content_hash,
            pending_vision_extraction=final_url.lower().endswith(".pdf"),
        )
        db.add(row)
        new_blocks.append(row)
    await db.flush()

    newsletter.last_scanned_at = datetime.now(UTC)
    summary = f"found {len(links)} link(s) on the page, {len(new_blocks)} new"

    retry_blocks = await pending_vision_retries(db, newsletter.id, new_blocks)
    if retry_blocks:
        summary += f", {len(retry_blocks)} retried"

    if new_blocks or retry_blocks:
        extraction_note = await extract_from_newsletter(db, newsletter, new_blocks, job_kind=_JOB_KIND, retry_blocks=retry_blocks)
        summary += f" · extraction: {extraction_note}"
        # Propagate whichever code extract_from_newsletter's own warning
        # carried, same reason smore_scan.py does - so it groups correctly
        # in Grafana rather than a generic re-wrap.
        warning_code = parse_warning(extraction_note)
        if warning_code:
            summary = f"WARNING[{warning_code}]: " + summary

    return summary
