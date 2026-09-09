from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from models import District, SchoolContentItem
from scheduler.registry import register_job
from services.district_calendar import fetch_district_calendar


@register_job(
    kind="district_calendar.scan",
    default_name="District calendar scan",
    default_cron="0 */12 * * *",  # every 12h - a public-source scan, kept fresh
    description="Fetches a district's own calendar feeds (.ics) - holidays, early dismissals, closures, and any grade-tier-specific schedules (e.g. an elementary specials rotation).",
    param_schema={"type": "object", "properties": {"district_id": {"type": "string"}}, "required": ["district_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    district_id = params.get("district_id")
    if not district_id:
        return "no district_id in params - nothing to do"

    district = (await db.execute(select(District).where(District.id == district_id))).scalar_one_or_none()
    if not district:
        return f"district {district_id} no longer exists"
    if not district.ics_feeds:
        return "district has no ics_feeds configured"

    events = []
    for feed in district.ics_feeds:
        feed_name, feed_url = feed.get("name"), feed.get("url")
        if not feed_url:
            continue
        # e.g. ["elementary"] for a feed that only applies to elementary
        # schools (a specials rotation calendar) - null/omitted means it
        # applies district-wide regardless of school type, same as the
        # main holidays/closures calendar.
        school_types = feed.get("school_types") or None
        for event in await fetch_district_calendar(feed_url):
            # Namespace the uid by feed - two different feeds could
            # otherwise coincidentally produce the same hash-based uid.
            event["external_uid"] = f"{feed_name}:{event['external_uid']}"
            event["applies_to_school_types"] = school_types
            events.append(event)

    if not events:
        return "WARNING: no events found in any configured ics feed"

    existing_by_uid = {
        d.external_uid: d
        for d in (
            await db.execute(
                select(SchoolContentItem).where(
                    SchoolContentItem.district_id == district_id,
                    SchoolContentItem.source == "ics_feed",
                    SchoolContentItem.external_uid.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    }

    created = updated = claimed = 0
    for event in events:
        row = existing_by_uid.get(event["external_uid"])
        if row:
            row.title = event["title"]
            row.description = event["description"]
            row.start_date = event["start_date"]
            row.end_date = event["end_date"]
            row.is_all_day = event["is_all_day"]
            row.applies_to_school_types = event["applies_to_school_types"]
            updated += 1
            continue

        # Cross-source dedup: a school's own newsletter may have already
        # reported this same district-wide date (e.g. "Labor Day") before
        # this feed was ever scanned. Claim that row instead of doubling
        # it - the ics feed is the more authoritative source for the exact
        # date, so it overwrites the newsletter-extracted text too. Only
        # applies to genuinely district-wide events (no school_types
        # filter) - a newsletter never reports a tier-specific schedule
        # like a rotation day, so there's nothing to claim there.
        newsletter_row = None
        if not event["applies_to_school_types"]:
            newsletter_row = (
                await db.execute(
                    select(SchoolContentItem).where(
                        SchoolContentItem.district_id == district_id,
                        SchoolContentItem.scope == "district",
                        SchoolContentItem.category == "event",
                        SchoolContentItem.source == "newsletter",
                        SchoolContentItem.start_date == event["start_date"],
                    )
                )
            ).scalars().first()
        if newsletter_row:
            newsletter_row.source = "ics_feed"
            newsletter_row.external_uid = event["external_uid"]
            newsletter_row.title = event["title"]
            newsletter_row.description = event["description"]
            newsletter_row.end_date = event["end_date"]
            newsletter_row.is_all_day = event["is_all_day"]
            claimed += 1
            continue

        db.add(
            SchoolContentItem(
                scope="district",
                district_id=district_id,
                category="event",
                title=event["title"],
                description=event["description"],
                start_date=event["start_date"],
                end_date=event["end_date"],
                is_all_day=event["is_all_day"],
                source="ics_feed",
                external_uid=event["external_uid"],
                applies_to_school_types=event["applies_to_school_types"],
            )
        )
        created += 1

    return f"district calendar: {created} new, {updated} updated, {claimed} deduped against newsletter items, {len(events)} total across {len(district.ics_feeds)} feed(s)"
