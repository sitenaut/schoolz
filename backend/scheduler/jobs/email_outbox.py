"""Scheduled job: retry outbound email that didn't go the first time
(services/mailer.py). Messages are sent right after the request that
queues them; this hourly pass catches a Gmail hiccup or a missing secret
and erases what's past its retention."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from scheduler.registry import register_job
from services import mailer


@register_job(
    kind="email.outbox",
    default_name="Send waiting email",
    default_cron="7 * * * *",
    default_params={},
    description="Retries outbound email that didn't send right away (5 tries, backing off) and erases old rows.",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    summary = await mailer.send_pending(limit=200)
    text = json.dumps(summary)
    if summary["waiting"]:
        return f"WARNING[email_not_configured]: SMTP_USERNAME/SMTP_PASSWORD aren't set - {summary['waiting']} waiting: {text}"
    if summary["failed"]:
        return f"WARNING[email_failed]: {summary['failed']} didn't send (will retry): {text}"
    return text
