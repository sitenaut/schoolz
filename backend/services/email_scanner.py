from datetime import datetime, timedelta, timezone

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
        since = (datetime.now(timezone.utc) - timedelta(days=scanner.lookback_days)).strftime("%Y/%m/%d")
        parts.append(f"after:{since}")
    return " ".join(parts)


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
    messages = fetch_all_messages_sync(service, query, skip_ids)

    processed_ok = 0
    for message in messages:
        headers = {h["name"].lower(): h["value"] for h in message.get("payload", {}).get("headers", [])}
        match = EmailScannerMatch(
            scanner_id=scanner.id,
            message_id=message["id"],
            sender=headers.get("from"),
            subject=headers.get("subject"),
            snippet=message.get("snippet"),
            processor_status="pending",
        )
        db.add(match)
        await db.flush()

        try:
            result = await processor.process(db, scanner, match, message)
            match.processor_status = result.status
            match.artifact_kind = result.artifact_kind
            match.artifact_id = result.artifact_id
            if result.status == "ok":
                processed_ok += 1
        except Exception as exc:
            match.processor_status = "error"
            match.processor_error = f"{type(exc).__name__}: {exc}"

        await db.commit()

    token.last_synced_at = datetime.now(timezone.utc)
    await db.commit()

    if processor.finalize and processed_ok:
        await processor.finalize(db, scanner, processed_ok)
        await db.commit()

    return f"scanned {len(messages)} new message(s), {processed_ok} processed ok"
