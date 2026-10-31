from datetime import UTC, date, datetime, timedelta

from sqlalchemy import cast, or_, select
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.ext.asyncio import AsyncSession

from models import EmailScanner, EmailScannerMatch, ScheduledJob, SchoolEmailMessage, SmoreNewsletter
from scheduler.cron import spread_default_smore_cron
from scheduler.job_names import newsletter_job_name
from services import email_links
from services.email_processors import ProcessorResult, register_processor

# Default cadence for a newsletter scan auto-scheduled this way - matches the
# default POST /smore-newsletters uses when someone creates one by hand.
_DEFAULT_SMORE_CRON = "0 8 * * 1"
_DEFAULT_SMORE_TIMEZONE = "America/New_York"
# Which scan a found link's newsletter gets, by source_type.
_JOB = {"smore": ("smore.scan", "Smore scan"), "mailchimp": ("mailchimp.scan", "Mailchimp scan")}
# How long an issue's scan keeps running after an email last brought its
# link (scheduler/jobs/smore_scan.py:issue_scan_over). A Smore issue is
# edited in place for a while; a sent Mailchimp campaign never changes, so
# two weekly tries are only there in case the first one fails.
_ISSUE_DAYS = {"smore": 28, "mailchimp": 14}


async def _known(db: AsyncSession, kind: str, url: str) -> SmoreNewsletter | None:
    # An older row may carry the `?ref=` a Smore email link had, or the
    # issue's name after its code (`/n/qf2pn-bret-harte-elementary-school`).
    urls = email_links.same_newsletter_urls(kind, url)
    suffixes = ("?%", "-%") if kind == "smore" else ("?%",)
    clause = or_(*(SmoreNewsletter.url == u for u in urls), *(SmoreNewsletter.url.like(f"{u}{s}") for u in urls for s in suffixes))
    return (await db.execute(select(SmoreNewsletter).where(clause).limit(1))).scalar_one_or_none()


def _stop_after(source_type: str, seen_at: datetime | None) -> str:
    seen = (seen_at or datetime.now(UTC)).date()
    return (seen + timedelta(days=_ISSUE_DAYS[source_type])).isoformat()


async def hand_enabled_stop_after(db: AsyncSession, newsletter: SmoreNewsletter) -> str | None:
    """The stop date for a scan an admin switches on by hand for an issue
    link an email brought (one left unassigned): the window this processor
    gives its own scans, counted from today, since a window counted from the
    email may already be over and the scan would end before its first fetch.
    None for anything else - a newsletter added by hand runs until someone
    turns it off, even one whose scan was deleted and is now re-enabled."""
    if newsletter.source_type not in _ISSUE_DAYS:
        return None
    hit = email_links.canonical(newsletter.url)
    if hit is None:
        return None
    links = cast(SchoolEmailMessage.newsletter_links, JSONB)
    urls = {hit[1], *email_links.same_newsletter_urls(*hit)}
    brought = select(SchoolEmailMessage.id).where(or_(*(links.contains([{"url": u}]) for u in urls)))
    if (await db.execute(brought.limit(1))).first() is None:
        return None
    return _stop_after(newsletter.source_type, None)


async def _renew(db: AsyncSession, newsletter: SmoreNewsletter, stop_after: str) -> None:
    """The link came again (a school reusing one Smore URL each week): its
    scan runs on. Only a scan this processor made has a date to move."""
    job = await db.get(ScheduledJob, newsletter.scheduled_job_id) if newsletter.scheduled_job_id else None
    if job is None or "stop_after" not in (job.params or {}):
        return
    if date.fromisoformat(stop_after) > date.fromisoformat(job.params["stop_after"]):
        job.params = {**job.params, "stop_after": stop_after}  # a new dict: plain JSON isn't change-tracked
        job.enabled = True


@register_processor("school_email")
async def _process(
    db: AsyncSession, scanner: EmailScanner, match: EmailScannerMatch, message: dict
) -> ProcessorResult:
    """Keeps the message's allowed newsletter links and nothing else of it
    (services/email_links.py). Each new link joins the shared newsletter
    list; when the scanner is dedicated to one school (EmailScanner.school_id
    - the normal case, a scanner filtering on that school's newsletter
    subject) it is attributed to that school and its scan scheduled at
    once. An undedicated scanner's link waits, unlinked, for an admin."""
    links = email_links.extract(message, scanner.link_kinds or [])
    counts = {"tracking_links": email_links.tracking_link_count(message)}
    if not links:
        return ProcessorResult(status="skipped", note="no newsletter links", counts=counts)

    counts.update(links=len(links), already_tracked=0, new_newsletters=0, waiting=0)
    for link in links:
        source_type = email_links.LINK_KINDS[link["kind"]].source_type
        known = await _known(db, link["kind"], link["url"])
        if known is not None:
            counts["already_tracked"] += 1
            await _renew(db, known, _stop_after(known.source_type if known.source_type in _ISSUE_DAYS else source_type, match.received_at))
            continue
        newsletter = SmoreNewsletter(
            url=link["url"], source_type=source_type, created_by_user_id=scanner.owner_user_id, school_id=scanner.school_id
        )
        db.add(newsletter)
        await db.flush()
        link["newsletter_id"] = newsletter.id
        counts["new_newsletters"] += 1
        if not scanner.school_id:
            counts["waiting"] += 1
        else:
            kind, label = _JOB[source_type]
            job = ScheduledJob(
                owner_user_id=scanner.owner_user_id,
                kind=kind,
                name=await newsletter_job_name(db, label, newsletter, scanner.owner_user_id, kind),
                cron_expr=spread_default_smore_cron(_DEFAULT_SMORE_CRON, newsletter.id),
                timezone=_DEFAULT_SMORE_TIMEZONE,
                params={"newsletter_id": newsletter.id, "stop_after": _stop_after(source_type, match.received_at)},
                enabled=True,
            )
            db.add(job)
            await db.flush()
            newsletter.scheduled_job_id = job.id

    record = SchoolEmailMessage(
        owner_user_id=scanner.owner_user_id,
        scanner_id=scanner.id,
        gmail_message_id=message["id"],
        received_at=match.received_at,
        newsletter_links=links,
    )
    db.add(record)
    await db.flush()
    return ProcessorResult(
        status="ok", artifact_kind="school_email_message", artifact_id=record.id, note=f"{len(links)} newsletter link(s)", counts=counts
    )
