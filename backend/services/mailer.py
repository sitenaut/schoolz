"""Outbound email: one place every message schoolz sends goes through.

Sent over SMTP with the Gmail account that already sends sign-up mail
(Supabase's SMTP settings): `SMTP_USERNAME` + `SMTP_PASSWORD` (a Google app
password, in the schoolz-prod vault). Unset - locally, or before the secret
is added - nothing is sent and messages wait in the outbox, so a missing
secret never breaks a request.

How a message travels:
1. `queue()` adds an `OutboundEmail` row in the caller's transaction, so it
   exists only if what caused it was committed.
2. The router hands `send_pending` to FastAPI's background tasks, which run
   after the response: a code arrives in seconds without the request
   waiting on Gmail.
3. The hourly `email.outbox` job retries what failed (5 tries, backing off)
   and tidies up.

Privacy: the address and body are encrypted while queued and erased the
moment a message is sent, fails for good or expires; only kind, status and
times remain, for 30 days. No tracking pixels or rewritten links - this is
plain text.
"""
from __future__ import annotations

import logging
import os
import smtplib
import ssl
from datetime import UTC, datetime, timedelta
from email.message import EmailMessage
from email.utils import formataddr, make_msgid

import anyio
from sqlalchemy import delete, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

import database
from models import OutboundEmail

logger = logging.getLogger(__name__)

MAX_ATTEMPTS = 5
KEEP_DAYS = 30


def _now() -> datetime:
    return datetime.now(UTC)


def settings() -> dict:
    username = os.getenv("SMTP_USERNAME", "").strip()
    return {
        "host": os.getenv("SMTP_HOST", "smtp.gmail.com").strip(),
        "port": int(os.getenv("SMTP_PORT", "587")),
        "username": username,
        "password": os.getenv("SMTP_PASSWORD", ""),
        "from_address": os.getenv("MAIL_FROM", "").strip() or username,
        "from_name": os.getenv("MAIL_FROM_NAME", "schoolz").strip(),
        "reply_to": os.getenv("MAIL_REPLY_TO", "").strip() or None,
    }


def configured() -> bool:
    s = settings()
    return bool(s["username"] and s["password"] and s["from_address"])


def queue(
    db: AsyncSession,
    *,
    kind: str,
    to: str,
    subject: str,
    body: str,
    user_id: str | None = None,
    ref: str | None = None,
    expires_in: timedelta | None = None,
) -> OutboundEmail:
    """Adds a message to the outbox in the caller's transaction (no
    commit). Pair it with `background_tasks.add_task(mailer.send_pending)`."""
    row = OutboundEmail(
        kind=kind,
        ref=ref,
        user_id=user_id,
        to_address=to.strip(),
        subject=subject,
        body=body.rstrip() + "\n",
        status="queued",
        attempts=0,
        next_attempt_at=_now(),
        expires_at=_now() + expires_in if expires_in else None,
    )
    db.add(row)
    return row


def _message(row: OutboundEmail, s: dict) -> EmailMessage:
    msg = EmailMessage()
    msg["From"] = formataddr((s["from_name"], s["from_address"]))
    msg["To"] = row.to_address
    msg["Subject"] = row.subject
    msg["Message-ID"] = make_msgid(domain=s["from_address"].rsplit("@", 1)[-1])
    if s["reply_to"]:
        msg["Reply-To"] = s["reply_to"]
    msg.set_content(row.body)
    return msg


def _send_sync(messages: list[EmailMessage], s: dict) -> list[str | None]:
    """One connection for the batch; per-message error text or None."""
    results: list[str | None] = []
    with smtplib.SMTP(s["host"], s["port"], timeout=20) as smtp:
        smtp.starttls(context=ssl.create_default_context())
        smtp.login(s["username"], s["password"])
        for msg in messages:
            try:
                smtp.send_message(msg)
                results.append(None)
            except smtplib.SMTPException as e:
                results.append(f"{type(e).__name__}: {e}"[:300])
    return results


def _erase(row: OutboundEmail) -> None:
    row.to_address = None
    row.body = None


async def send_pending(limit: int = 50) -> dict:
    """Sends what's due. Safe to run from several places at once: rows are
    claimed with SKIP LOCKED. Opens its own session (it runs after the
    request's has closed)."""
    summary = {"sent": 0, "failed": 0, "expired": 0, "waiting": 0, "purged": 0}
    async with database.SessionLocal() as db:
        stamp = _now()
        rows = (
            await db.execute(
                select(OutboundEmail)
                .where(OutboundEmail.status == "queued", OutboundEmail.next_attempt_at <= stamp)
                .order_by(OutboundEmail.created_at)
                .limit(limit)
                .with_for_update(skip_locked=True)
            )
        ).scalars().all()
        due = []
        for row in rows:
            if row.expires_at and row.expires_at <= stamp:
                row.status = "expired"
                _erase(row)
                summary["expired"] += 1
            else:
                due.append(row)
        if due and not configured():
            summary["waiting"] = len(due)
            logger.warning("email_not_configured", extra={"waiting": len(due)})
            due = []
        if due:
            s = settings()
            try:
                results = await anyio.to_thread.run_sync(_send_sync, [_message(r, s) for r in due], s)
            except (OSError, smtplib.SMTPException) as e:
                # Couldn't connect or log in: every message waits for the retry.
                results = [f"{type(e).__name__}: {e}"[:300]] * len(due)
            for row, error in zip(due, results, strict=True):
                row.attempts += 1
                if error is None:
                    row.status, row.sent_at = "sent", _now()
                    _erase(row)
                    summary["sent"] += 1
                    logger.info("email_sent", extra={"email_id": row.id, "kind": row.kind})
                else:
                    row.last_error = error
                    if row.attempts >= MAX_ATTEMPTS:
                        row.status = "failed"
                        _erase(row)
                    else:
                        row.next_attempt_at = _now() + timedelta(minutes=5 * 2 ** row.attempts)
                    summary["failed"] += 1
                    logger.warning("email_failed", extra={"email_id": row.id, "kind": row.kind, "attempts": row.attempts, "error": error})
        result = await db.execute(
            delete(OutboundEmail).where(
                OutboundEmail.created_at < stamp - timedelta(days=KEEP_DAYS),
                or_(OutboundEmail.status != "queued", OutboundEmail.expires_at.is_not(None)),
            )
        )
        summary["purged"] = result.rowcount or 0
        await db.commit()
    return summary


async def send_pending_quietly() -> None:
    """For background tasks: a failure here must never surface as an error
    after the response has gone (the hourly job retries)."""
    try:
        await send_pending()
    except Exception:  # noqa: BLE001 - logged, retried by email.outbox
        logger.exception("email_send_pending_failed")
