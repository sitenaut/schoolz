from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import SmoreNewsletter
from scheduler.errors import parse_warning
from scheduler.jobs.smore_scan import issue_scan_over, store_new_blocks
from scheduler.registry import register_job
from services.content_extractor import extract_from_newsletter
from services.mailchimp_parser import fetch_and_parse

_JOB_KIND = "mailchimp.scan"


@register_job(
    kind=_JOB_KIND,
    default_name="Mailchimp newsletter scan",
    default_cron="0 8 * * 1",  # Monday mornings, same cadence as Smore
    description="Fetches a sent Mailchimp campaign's public page and stores any content blocks not seen before.",
    param_schema={
        "type": "object",
        "properties": {
            "newsletter_id": {"type": "string"},
            # Set only on a scan the email scanner made for one issue: see issue_scan_over.
            "stop_after": {"type": "string", "format": "date"},
        },
        "required": ["newsletter_id"],
    },
)
async def run(db: AsyncSession, params: dict) -> str | None:
    newsletter_id = params.get("newsletter_id")
    if not newsletter_id:
        return "no newsletter_id in params - nothing to do"

    newsletter = (await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.id == newsletter_id))).scalar_one_or_none()
    if not newsletter:
        return f"newsletter {newsletter_id} no longer exists"
    over = await issue_scan_over(db, newsletter, params)
    if over:
        return over

    blocks = await fetch_and_parse(newsletter.url)
    newsletter.last_scanned_at = datetime.now(UTC)
    if not blocks:
        # A sent campaign always has content; none means Mailchimp took the
        # page down (it redirects to a page about Mailchimp) - the link needs
        # attention, the same signal as an expired Smore link.
        return f"WARNING[mailchimp_no_blocks]: fetched 0 blocks from {newsletter.url} - campaign page may have been taken down"

    new_blocks = await store_new_blocks(db, newsletter, blocks)
    summary = f"fetched {len(blocks)} block(s), {len(new_blocks)} new"
    if new_blocks:
        extraction_note = await extract_from_newsletter(db, newsletter, new_blocks, job_kind=_JOB_KIND)
        summary += f" · extraction: {extraction_note}"
        warning_code = parse_warning(extraction_note)
        if warning_code:
            summary = f"WARNING[{warning_code}]: " + summary
    return summary
