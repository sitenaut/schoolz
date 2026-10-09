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
# Events a reviewer published from a community submission. No job lists this
# source, so without the exemption the next job edit would delete them all.
COMMUNITY_SOURCE = "community"
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
    "yodel_sources",
    "tribe_sources",
    "ccls_sources",
    "libcal_sources",
    "bibliocommons_sources",
    "mec_sources",
    "drupal_fullcalendar_sources",
    "theatre_sources",
    "ludus_sources",
    "placewise_sources",
    "patch_sources",
    "dostuff_sources",
    "runsignup_sources",
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
    keep.add(COMMUNITY_SOURCE)
    result = await db.execute(delete(LocalEvent).where(LocalEvent.source.not_in(keep)))
    return result.rowcount or 0
