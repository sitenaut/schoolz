"""Stable, groupable failure reasons for scheduled jobs.

Today a failure is only `f"{type(exc).__name__}: {exc}"` plus a traceback -
that can't be grouped or alerted on cleanly. See docs/OBSERVABILITY_PLAN.md
Phase 3.
"""
import logging
import re

import anthropic
import httpx
import sqlalchemy.exc

import observability

logger = logging.getLogger(__name__)

# stage: "fetch" | "parse" | "extract" | "persist"


class ScanError(Exception):
    """Raise from a handler/parser to give a failure a stable, groupable
    reason instead of falling back to classify_exception's generic mapping."""

    def __init__(self, code: str, message: str, *, stage: str, **context):
        super().__init__(message)
        self.code = code
        self.stage = stage
        self.context = context


_RETRYABLE_STATUSES = {502, 503, 504}

# Warning codes emitted by scheduler/jobs/*.py handlers via "WARNING[<code>]: ...".
_WARNING_RE = re.compile(r"^WARNING\[([a-z_]+)\]:")


def parse_warning(text: str | None) -> str | None:
    """Extracts the warning code from a handler's `"WARNING[<code>]: ..."`
    return value, falling back to "unspecified" for a bare `"WARNING:"`.
    Returns None if `text` isn't a warning at all."""
    if not text or not text.startswith("WARNING"):
        return None
    match = _WARNING_RE.match(text)
    return match.group(1) if match else "unspecified"


def classify_exception(exc: BaseException) -> tuple[str, str]:
    """Returns (code, stage). Walks __cause__/__context__ since scraper_client
    and httpx re-raise, so the ScanError or classifiable exception isn't
    always the outermost one."""
    seen: set[int] = set()
    current: BaseException | None = exc
    while current is not None and id(current) not in seen:
        seen.add(id(current))

        if isinstance(current, ScanError):
            return current.code, current.stage

        if isinstance(current, httpx.HTTPStatusError):
            status = current.response.status_code
            if status == 502:
                return "site_did_not_load", "fetch"
            if status in (503, 504):
                return "scraper_unavailable", "fetch"
            return "source_http_error", "fetch"
        if isinstance(current, httpx.TimeoutException):
            return "scraper_timeout", "fetch"
        if isinstance(current, httpx.TransportError):
            return "scraper_unavailable", "fetch"

        if isinstance(current, anthropic.RateLimitError):
            return "llm_rate_limited", "extract"
        if isinstance(current, anthropic.APIError):
            return "llm_api_error", "extract"

        if isinstance(current, sqlalchemy.exc.TimeoutError):
            return "db_pool_timeout", "persist"
        if isinstance(current, sqlalchemy.exc.DBAPIError):
            return "db_error", "persist"

        current = current.__cause__ or current.__context__

    return "unknown", "unknown"


def record_parse_issue(job_kind: str, code: str, **context) -> None:
    """Logs a non-fatal problem found inside an otherwise-successful scan
    and increments the schoolz.parse.issues counter. Never pass email
    bodies or anything from school_email_messages as context - keep values
    short (url, school_id, selector/sample <=200 chars)."""
    logger.warning("parse_issue", extra={"job_kind": job_kind, "code": code, **context})
    observability.parse_issues_total.add(1, {"job.kind": job_kind, "code": code})
