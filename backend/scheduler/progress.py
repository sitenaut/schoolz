import contextvars
import json
import logging

from sqlalchemy import text

from database import SessionLocal

logger = logging.getLogger(__name__)

# Set by runner.py around the handler call so a job handler can checkpoint
# without needing run_id threaded through every function signature (every
# registered handler is a fixed `(db, params) -> str | None`, see
# scheduler/registry.py). Opt-in per handler - only multi-step handlers
# (e.g. local_events' per-source loop) need to call checkpoint().
_current_run_id: contextvars.ContextVar[str | None] = contextvars.ContextVar("current_run_id", default=None)


def bind(run_id: str) -> contextvars.Token:
    return _current_run_id.set(run_id)


def unbind(token: contextvars.Token) -> None:
    _current_run_id.reset(token)


async def checkpoint(summary: dict) -> None:
    """Persist an in-progress run summary so a crash mid-handler (OOM kill,
    deploy, crash) leaves real forensic detail behind instead of only the
    reaper's generic "process exited mid-run" message. The reaper
    (scheduler/entrypoint.py) never touches log_excerpt, so whatever was
    written here survives a reap untouched.

    Uses its own short-lived session rather than the handler's `db` -
    the whole point is for this to already be durable by the time a crash
    would roll the handler's own transaction back.
    """
    run_id = _current_run_id.get()
    if not run_id:
        return
    try:
        async with SessionLocal() as db:
            await db.execute(
                text(
                    "UPDATE job_runs SET log_excerpt = :excerpt, last_progress_at = now() "
                    "WHERE id = :id AND status = 'running'"
                ),
                {"id": run_id, "excerpt": json.dumps({"in_progress": True, **summary})[:8000]},
            )
            await db.commit()
    except Exception:
        logger.exception("progress_checkpoint_failed", extra={"run_id": run_id})
