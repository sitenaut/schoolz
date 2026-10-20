"""Writes each model call's token counts to `llm_usage`, for the daily cost
report. Called from observability.record_llm_call, so every metered call is
here too.

The write happens in a background task with its own session: record_llm_call
is synchronous and runs inside scans and requests, and a slow or failed
insert must never slow or fail the call it describes. A row lost to a crash
under-reports by one call; nothing else depends on it.
"""
from __future__ import annotations

import asyncio
import logging
import os

import database
from models import LlmUsage

logger = logging.getLogger(__name__)

_PENDING: set[asyncio.Task] = set()


def note(purpose: str, model: str, usage, stop_reason: str | None) -> None:
    """Schedules one row. Skipped outside an event loop, and under pytest,
    where a task outliving its test would write into the next test's
    transaction (tests call write() directly)."""
    if usage is None or os.getenv("PYTEST_CURRENT_TEST"):
        return
    try:
        loop = asyncio.get_running_loop()
    except RuntimeError:
        return
    row = {
        "purpose": purpose[:64],
        "model": (model or "unknown")[:100],
        "service": os.getenv("OTEL_SERVICE_NAME") or os.getenv("FLY_PROCESS_GROUP"),
        "stop_reason": (stop_reason or None) and str(stop_reason)[:40],
        "input_tokens": int(getattr(usage, "input_tokens", 0) or 0),
        "output_tokens": int(getattr(usage, "output_tokens", 0) or 0),
        "cache_read_tokens": int(getattr(usage, "cache_read_input_tokens", 0) or 0),
        "cache_write_tokens": int(getattr(usage, "cache_creation_input_tokens", 0) or 0),
    }
    task = loop.create_task(write(row))
    _PENDING.add(task)
    task.add_done_callback(_PENDING.discard)


async def write(row: dict) -> None:
    try:
        async with database.SessionLocal() as db:
            db.add(LlmUsage(**row))
            await db.commit()
    except Exception:  # noqa: BLE001 - the ledger never breaks a model call
        logger.warning("llm_ledger_write_failed", exc_info=True)
