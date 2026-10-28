"""Scheduled job: Neighborz's timers (bills/flow.py:settle).

Requests apply them too, the moment anyone looks; this makes them stick
within the hour when nobody does, and sends the "your hold ends soon"
reminders, which no request would."""
from __future__ import annotations

import json

from sqlalchemy.ext.asyncio import AsyncSession

from bills import flow
from scheduler.registry import register_job
from services import mailer


@register_job(
    kind="bills.sweep",
    default_name="Neighborz: holds, answers and erasing",
    default_cron="23 * * * *",
    default_params={},
    description="Ends 24-hour holds, closes unanswered and old bills, erases closed bills' account numbers, sends the reminders.",
)
async def run(db: AsyncSession, params: dict) -> str | None:
    summary = await flow.settle(db)
    summary["hold_warnings"] = await flow.warn_ending_holds(db)
    summary["send"] = await mailer.send_pending(limit=200)
    return json.dumps(summary)
