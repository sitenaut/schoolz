"""Slows a scan that keeps finding nothing.

About a fifth of the per-school documents and roster scans end in
WARNING[no_documents_found] / WARNING[no_staff_found] run after run: the site
has no handbook page, or a roster this parser can't read. Re-fetching them on
every fire costs a Chromium page load each for no change. After
STREAK_LENGTH identical empty results a cron or catch-up fire is skipped
unless the last real run is MIN_GAP_DAYS old, which on a biweekly job means
every other fire. Manual and first runs always go, and one run that finds
something ends the streak. Pure, so it is unit-testable without a DB.
"""
from datetime import datetime, timedelta

# kind -> the warning codes that mean "fetched fine, there was nothing there".
# school_info's missing-fields warning is deliberately absent: it still
# updates the fields it did find.
EMPTY_CODES: dict[str, frozenset[str]] = {
    "documents.scan": frozenset({"no_documents_found"}),
    "staff_roster.scan": frozenset({"no_staff_found"}),
}
STREAK_LENGTH = 3
MIN_GAP_DAYS = 27
BACKOFF_TRIGGERS = frozenset({"cron", "catchup"})


def back_off_reason(kind: str, triggered_by: str, recent: list[tuple[str, str | None, datetime]], now: datetime) -> str | None:
    """`recent` is the job's latest runs, newest first, as (status,
    error_code, started_at), skipped runs already left out. Returns why this
    fire should be skipped, or None to run it."""
    codes = EMPTY_CODES.get(kind)
    if not codes or triggered_by not in BACKOFF_TRIGGERS or len(recent) < STREAK_LENGTH:
        return None
    streak = recent[:STREAK_LENGTH]
    if not all(status == "warning" and code in codes for status, code, _ in streak):
        return None
    last_started = streak[0][2]
    if now - last_started >= timedelta(days=MIN_GAP_DAYS):
        return None
    return (
        f"backed off: the last {STREAK_LENGTH} runs all ended {streak[0][1]}; "
        f"next real run once the last one (started {last_started:%Y-%m-%d}) is {MIN_GAP_DAYS} days old. "
        "Run it now from the jobs page after fixing the source."
    )
