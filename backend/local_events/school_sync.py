"""Publishes a source's school-tagged local events (`RawEvent.school_slug`)
as public `SchoolContentItem` rows on that school's own page, in addition to
the normal local_events row a signed-in user's local-events feed shows. A
school's own ticketed show (a school theatre program on a shared ticketing
site, say) is genuinely both at once - see `RawEvent.school_slug` and
`sources/ludus.py`.

Upsert pattern copied from `services/school_events_doc.py`: query existing
rows for (school, source), key by external_uid - here, the RawEvent's own
globally-unique `source_event_id`, already stable across re-scans, so no
separate hash is needed - upsert what's seen, delete what vanished.
"""
from __future__ import annotations

import logging
from collections import defaultdict

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem

from .sources.base import RawEvent

logger = logging.getLogger(__name__)

SOURCE = "local_events"


def group_by_school(all_raws: list[RawEvent]) -> dict[str, list[RawEvent]]:
    grouped: dict[str, list[RawEvent]] = defaultdict(list)
    for raw in all_raws:
        if raw.school_slug:
            grouped[raw.school_slug].append(raw)
    return grouped


async def sync_school_content(db: AsyncSession, events_by_school: dict[str, list[RawEvent]]) -> dict:
    """events_by_school: school slug -> every RawEvent tagged for it across
    the whole pipeline run (not just one source), so pruning a vanished show
    is correct even if a school's slug were ever tagged from two sources."""
    created = updated = removed = 0
    unknown_slugs: set[str] = set()
    for slug, raws in events_by_school.items():
        school = (await db.execute(select(School).where(School.slug == slug))).scalar_one_or_none()
        if school is None:
            # A mistyped or since-renamed slug shouldn't sink the whole run -
            # it's a config error to fix, not a reason to drop every event.
            unknown_slugs.add(slug)
            continue
        existing = {
            r.external_uid: r
            for r in (
                await db.execute(
                    select(SchoolContentItem).where(
                        SchoolContentItem.school_id == school.id,
                        SchoolContentItem.source == SOURCE,
                    )
                )
            ).scalars()
        }
        seen: set[str] = set()
        for raw in raws:
            uid = raw.source_event_id
            if uid in seen:
                continue
            seen.add(uid)
            row = existing.get(uid)
            if row is None:
                row = SchoolContentItem(
                    scope="school", school_id=school.id, source=SOURCE, external_uid=uid, category="event",
                )
                db.add(row)
                created += 1
            else:
                updated += 1
            row.title = raw.title[:300]
            row.description = raw.description
            row.start_date = raw.start_time
            row.end_date = raw.end_time
            row.is_all_day = raw.all_day
            row.link_url = raw.url
            row.is_current = True
        for uid, row in existing.items():
            if uid not in seen:
                await db.delete(row)
                removed += 1
    if unknown_slugs:
        logger.warning("local_events_unknown_school_slug", extra={"slugs": sorted(unknown_slugs)})
    return {"created": created, "updated": updated, "removed": removed, "unknown_slugs": sorted(unknown_slugs)}
