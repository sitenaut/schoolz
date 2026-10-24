from datetime import UTC, datetime, timedelta

import anyio
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from gmail_client import fetch_all_messages_sync, get_gmail_service
from models import EmailScanner, EmailScannerMatch, GmailToken
from services.email_processors import get_processor


def build_gmail_query(scanner: EmailScanner) -> str:
    parts = []
    for field, values in (("from", scanner.from_contains), ("subject", scanner.subject_contains)):
        if values:
            parts.append("(" + " OR ".join(f"{field}:{v}" for v in values) + ")")
    if scanner.body_contains:
        # Gmail has no explicit "body:" operator - bare terms already match
        # subject+body, which is what we want here.
        parts.append("(" + " OR ".join(f'"{v}"' for v in scanner.body_contains) + ")")
    if scanner.raw_query:
        parts.append(scanner.raw_query)
    if scanner.lookback_days:
        since = (datetime.now(UTC) - timedelta(days=scanner.lookback_days)).strftime("%Y/%m/%d")
        parts.append(f"after:{since}")
    return " ".join(parts)


def _received_at(message: dict) -> datetime | None:
    """Gmail's own arrival time (epoch ms), so no header has to be read."""
    try:
        return datetime.fromtimestamp(int(message["internalDate"]) / 1000, tz=UTC)
    except (KeyError, TypeError, ValueError):
        return None


class ScannerNotReady(RuntimeError):
    pass


async def run_scanner(db: AsyncSession, scanner: EmailScanner) -> str:
    processor = get_processor(scanner.purpose)
    if not processor:
        raise ScannerNotReady(f"Unknown processor purpose: {scanner.purpose}")

    token_result = await db.execute(
        select(GmailToken).where(
            GmailToken.user_id == scanner.owner_user_id, GmailToken.google_email == scanner.google_email
        )
    )
    token = token_result.scalar_one_or_none()
    if not token:
        raise ScannerNotReady(f"No connected Gmail account for {scanner.google_email}")

    service = await get_gmail_service(db, token)
    await db.commit()  # persist any token refresh from get_gmail_service

    seen_result = await db.execute(
        select(EmailScannerMatch.message_id).where(EmailScannerMatch.scanner_id == scanner.id)
    )
    skip_ids = {row[0] for row in seen_result.all()}

    query = build_gmail_query(scanner)
    # Off the event loop, like every other Gmail call (gmail_client.py): a
    # year's lookback is hundreds of blocking requests, which froze every
    # other job in the scheduler. One thread, so httplib2 isn't shared.
    messages = await anyio.to_thread.run_sync(fetch_all_messages_sync, service, query, skip_ids)

    processed_ok = 0
    for message in messages:
        # Only the id and when it arrived: never the sender, subject or
        # Gmail's snippet of the body (services/email_links.py says why).
        match = EmailScannerMatch(
            scanner_id=scanner.id,
            message_id=message["id"],
            received_at=_received_at(message),
            processor_status="pending",
        )
        db.add(match)
        await db.flush()

        try:
            # In a SAVEPOINT: a DB error (a scan job's name already taken,
            # say) used to fail the session, so the commit below raised and
            # every run stopped at this message, never reaching the rest.
            async with db.begin_nested():
                result = await processor.process(db, scanner, match, message)
            match.processor_status = result.status
            match.artifact_kind = result.artifact_kind
            match.artifact_id = result.artifact_id
            if result.status == "ok":
                processed_ok += 1
        except Exception as exc:
            match.processor_status = "error"
            # The type only: an exception's message can quote the email.
            match.processor_error = type(exc).__name__

        await db.commit()

    token.last_synced_at = datetime.now(UTC)
    await db.commit()

    if processor.finalize and processed_ok:
        await processor.finalize(db, scanner, processed_ok)
        await db.commit()

    return f"scanned {len(messages)} new message(s), {processed_ok} processed ok"
