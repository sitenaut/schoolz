import re
from datetime import datetime
from email.utils import parsedate_to_datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gmail_client import extract_body_text, extract_header
from models import EmailScanner, EmailScannerMatch, ScheduledJob, SchoolEmailMessage, SmoreNewsletter
from services.email_processors import ProcessorResult, register_processor

# Default cadence for a Smore scan auto-scheduled this way - matches the
# default POST /smore-newsletters uses when a guardian creates one by hand.
_DEFAULT_SMORE_CRON = "0 8 * * 1"
_DEFAULT_SMORE_TIMEZONE = "America/New_York"

# Known hosted-newsletter platforms whose links are worth following up on
# later (Smore is the one we've confirmed schools in the district actually
# use - see CLAUDE.md for why parsing these needs a headless browser + a
# vision pass for image-only announcement blocks). Matches any subdomain,
# including out.smore.com email tracking-redirect links.
_NEWSLETTER_LINK_RE = re.compile(r"https?://[a-z0-9.-]*smore\.com/[^\s\"'<>)\]]+", re.IGNORECASE)


def _parse_date(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return parsedate_to_datetime(value)
    except (TypeError, ValueError):
        return None


@register_processor("school_email")
async def _process(
    db: AsyncSession, scanner: EmailScanner, match: EmailScannerMatch, message: dict
) -> ProcessorResult:
    body_text = extract_body_text(message)
    found_urls = list(dict.fromkeys(_NEWSLETTER_LINK_RE.findall(body_text)))
    newsletter_links = [{"url": url, "fetched": False} for url in found_urls]

    # Surface each discovered link in the shared SmoreNewsletter list. When
    # the scanner is dedicated to one school (EmailScanner.school_id set -
    # the normal case: a scanner named "X SMORE" filtering on that school's
    # newsletter subject), attribute the link to that school and schedule
    # scanning immediately - the scanner's own school_id is already an
    # explicit, deliberate choice, so there's nothing left to ask about.
    # An undedicated scanner still leaves the link unlinked/unscheduled for
    # a guardian to opt in by hand, same as before.
    for url in found_urls:
        existing = await db.execute(select(SmoreNewsletter).where(SmoreNewsletter.url == url))
        if existing.scalar_one_or_none():
            continue

        newsletter = SmoreNewsletter(url=url, created_by_user_id=scanner.owner_user_id, school_id=scanner.school_id)
        db.add(newsletter)

        if scanner.school_id:
            await db.flush()
            job = ScheduledJob(
                owner_user_id=scanner.owner_user_id,
                kind="smore.scan",
                name=f"Smore scan: {url}",
                cron_expr=_DEFAULT_SMORE_CRON,
                timezone=_DEFAULT_SMORE_TIMEZONE,
                params={"newsletter_id": newsletter.id},
                enabled=True,
            )
            db.add(job)
            await db.flush()
            newsletter.scheduled_job_id = job.id

    record = SchoolEmailMessage(
        owner_user_id=scanner.owner_user_id,
        scanner_id=scanner.id,
        gmail_message_id=message["id"],
        sender=extract_header(message, "From"),
        subject=extract_header(message, "Subject"),
        received_at=_parse_date(extract_header(message, "Date")),
        body_text=body_text,
        newsletter_links=newsletter_links,
    )
    db.add(record)
    await db.flush()

    note = f"captured{' · ' + str(len(newsletter_links)) + ' newsletter link(s)' if newsletter_links else ''}"
    return ProcessorResult(status="ok", artifact_kind="school_email_message", artifact_id=record.id, note=note)
