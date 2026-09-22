"""Remove events whose source no local_events.refresh job still lists.

Events are keyed by source name (every adapter stamps RawEvent.source with
the configured `name`), not by job, so this checks names across *all*
remaining jobs: two jobs listing the same source (an import from billz next
to the seeded job) keep its events until neither does. Disabling a job is
not removing it - its sources still count."""

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LocalEvent, ScheduledJob

KIND = "local_events.refresh"
SOURCE_KEYS = (
    "evvnt_sources",
    "json_sources",
    "ical_sources",
    "rss_sources",
    "gcal_sources",
    "listing_page_sources",
    "sitemap_sources",
    "deyra_schedule_sources",
    "scraper_sources",
)


def source_names(params: dict | None) -> set[str]:
    names: set[str] = set()
    for key in SOURCE_KEYS:
        for entry in (params or {}).get(key) or []:
            if isinstance(entry, dict) and entry.get("name"):
                names.add(str(entry["name"]))
    return names


async def prune_orphaned_events(db: AsyncSession) -> int:
    """Deletes events from sources no remaining job lists; returns how many.
    Doesn't commit - the caller's transaction covers it."""
    params = (await db.execute(select(ScheduledJob.params).where(ScheduledJob.kind == KIND))).scalars().all()
    keep: set[str] = set()
    for p in params:
        keep |= source_names(p)
    stmt = delete(LocalEvent)
    if keep:
        stmt = stmt.where(LocalEvent.source.not_in(keep))
    result = await db.execute(stmt)
    return result.rowcount or 0
