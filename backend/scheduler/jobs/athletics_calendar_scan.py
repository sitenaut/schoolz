from datetime import date, datetime, time, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import and_, delete, false, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import School, SchoolContentItem
from scheduler.registry import register_job
from services import digitalsports, gobound
from services.arbiter import (
    entity_id_from_athletics_url,
    fetch_events,
    fetch_statuses,
    games_for_school,
    is_middle_school_team,
)

_ET = ZoneInfo("America/New_York")

# A season runs a few months; wide enough either direction to cover a
# season already in progress and next season's early games without
# fetching a year's worth of empty months.
_WINDOW_PAST_DAYS = 30
_WINDOW_FUTURE_DAYS = 180


# Games are hidden from the general calendar (dozens a week). A school's own
# events on its Arbiter calendar (Gateway: field trips, Financial Aid Night)
# are shown only when the school is switched on (School.arbiter_events_calendar):
# elsewhere an Arbiter "event" is team business - open gyms, team dinners,
# tryouts - which belongs with the games.
_SOURCES = ("arbiter_athletics", "arbiter_events", digitalsports.SOURCE, gobound.SOURCE)


def _source(event: dict, school: School) -> str:
    if event.get("source"):
        return event["source"]
    return "arbiter_events" if event.get("kind") == "event" and school.arbiter_events_calendar else "arbiter_athletics"


def _placement(event: dict, school: School) -> dict:
    """Whose item it is. A shown event of a school whose Arbiter calendar is its
    whole district's (Audubon) is district-scoped, so every school in the
    district shows it; everything else belongs to the school."""
    if _source(event, school) == "arbiter_events" and school.arbiter_events_district_wide and school.district_id:
        return {"scope": "district", "district_id": school.district_id, "school_id": None}
    return {"scope": "school", "district_id": None, "school_id": school.id}


async def _store_listed(db: AsyncSession, school: School, source: str, events: list[dict], start: date, end: date, retire: tuple[str, ...] = ()) -> tuple[int, int, int, int]:
    """Stores a feed that lists every game in the window: (created, updated,
    removed, retired). A rescheduled game's old entry (and a deleted one)
    disappears from the listing, so unlike Arbiter's feed, rows in the window
    that are no longer listed are removed rather than left on the calendar.
    `retire` names the sources this one replaces at the school: their games in
    the window would show twice."""
    uids = {e["external_uid"] for e in events}
    in_window = (
        SchoolContentItem.school_id == school.id,
        SchoolContentItem.start_date >= datetime.combine(start, time.min, _ET),
        SchoolContentItem.start_date <= datetime.combine(end, time.max, _ET),
    )
    removed = (await db.execute(delete(SchoolContentItem).where(*in_window, SchoolContentItem.source == source, SchoolContentItem.external_uid.not_in(uids)))).rowcount
    retired = (await db.execute(delete(SchoolContentItem).where(*in_window, SchoolContentItem.source.in_(retire)))).rowcount if retire else 0
    existing = {
        row.external_uid: row
        for row in (
            await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id, SchoolContentItem.source == source, SchoolContentItem.external_uid.in_(uids)))
        )
        .scalars()
        .all()
    }
    created = updated = 0
    for event in events:
        row = existing.get(event["external_uid"])
        fields = dict(
            title=event["title"], description=event["description"], start_date=event["start_date"], end_date=event["end_date"], is_all_day=event["is_all_day"]
        )
        if row:
            for name, value in fields.items():
                setattr(row, name, value)
            updated += 1
            continue
        db.add(SchoolContentItem(**_placement(event, school), category="event", source=source, external_uid=event["external_uid"], **fields))
        created += 1
    return created, updated, removed, retired


async def _siblings(db: AsyncSession, school: School) -> list[School]:
    if not school.district_id or school.school_type not in ("middle", "high"):
        return []
    return list((await db.execute(select(School).where(School.district_id == school.district_id, School.id != school.id))).scalars().all())


async def _run_digitalsports(db: AsyncSession, school: School, host: str, start: date, end: date) -> str | None:
    events = await digitalsports.fetch_events(host, start, end)
    # One site can list a high school and its middle school together (Robbinsville,
    # teams named "Soccer - Boys Middle School"). Only then is the team a split.
    if any(s.school_type in ("middle", "high") and digitalsports.host_from_athletics_url(s.athletics_url) == host for s in await _siblings(db, school)):
        events = [e for e in events if e["kind"] != "game" or is_middle_school_team(e) == (school.school_type == "middle")]
    if not events:
        return f"WARNING[no_digitalsports_events]: no games found on {host}.digitalsports.com for this school"
    for event in events:
        event["source"] = digitalsports.SOURCE
    created, updated, removed, _ = await _store_listed(db, school, digitalsports.SOURCE, events, start, end)
    return f"athletics calendar (digitalsports): {created} new, {updated} updated, {removed} removed, {len(events)} total"


async def _run_gobound(db: AsyncSession, school: School, url: str, start: date, end: date) -> str | None:
    events = await gobound.fetch_events(url, start, end)
    # A high school's GoBound page carries its middle school's teams too
    # (Kingsway: "8th Grade", "MS Red"). A middle school pointed at its high
    # school's feed shows only those; a high school whose middle school has a
    # GoBound feed of its own leaves them to it.
    siblings = [s for s in await _siblings(db, school) if gobound.feed_url(s.athletics_url)]
    if school.school_type == "middle" and any(s.school_type == "high" and gobound.school_key(s.athletics_url) == gobound.school_key(url) for s in siblings):
        events = [e for e in events if gobound.is_middle_school_team(e)]
    elif school.school_type == "high" and any(s.school_type == "middle" for s in siblings):
        events = [e for e in events if not gobound.is_middle_school_team(e)]
    if not events:
        return "WARNING[no_gobound_events]: no games found in the GoBound calendar feed for this school"
    for event in events:
        event["source"] = gobound.SOURCE
    # A school moved to GoBound from ArbiterLive or DigitalSports still has
    # that source's games stored; the feed lists the same games.
    created, updated, removed, retired = await _store_listed(db, school, gobound.SOURCE, events, start, end, retire=("arbiter_athletics", digitalsports.SOURCE))
    summary = f"athletics calendar (gobound): {created} new, {updated} updated, {removed} removed, {len(events)} total"
    return f"{summary}, {retired} from the school's previous source retired" if retired else summary


@register_job(
    kind="athletics_calendar.scan",
    default_name="Athletics calendar scan",
    default_cron="0 */12 * * *",  # a public-source scan, same cadence as the other calendar scans
    description=(
        "Fetches a school's game schedule from ArbiterLive (School.athletics_url, when it's a /m/team/<id> page) or from a "
        "<school>.digitalsports.com site (read week by week; source=digitalsports, same hidden-by-default treatment) or from a "
        "GoBound calendar subscription link (gobound.com/<state>/schools/<slug>/calendar/ical/<token>, competitions only; source=gobound) - "
        "every sport/level combined. Games are tagged source=arbiter_athletics and off by default in the general calendar "
        "(dozens a week would crowd out real deadlines); visible via the 'Show sports schedule' toggle. A school's own "
        "events on the same calendar (/m/event/<id>: Gateway's field trips and family nights) are source=arbiter_events and shown only for a school with arbiter_events_calendar set."
    ),
    param_schema={"type": "object", "properties": {"school_id": {"type": "string"}}, "required": ["school_id"]},
)
async def run(db: AsyncSession, params: dict) -> str | None:
    school_id = params.get("school_id")
    if not school_id:
        return "no school_id in params - nothing to do"

    school = (await db.execute(select(School).where(School.id == school_id))).scalar_one_or_none()
    if not school:
        return f"school {school_id} no longer exists"

    entity_id = entity_id_from_athletics_url(school.athletics_url)
    ds_host = None if entity_id else digitalsports.host_from_athletics_url(school.athletics_url)
    gb_feed = None if entity_id or ds_host else gobound.feed_url(school.athletics_url)
    if not entity_id and not ds_host and not gb_feed:
        return "school's athletics_url isn't an ArbiterLive team page (/m/team/<id>), a digitalsports.com site or a GoBound calendar link - nothing to fetch"

    today = date.today()
    start, end = today - timedelta(days=_WINDOW_PAST_DAYS), today + timedelta(days=_WINDOW_FUTURE_DAYS)
    if ds_host:
        return await _run_digitalsports(db, school, ds_host, start, end)
    if gb_feed:
        return await _run_gobound(db, school, gb_feed, start, end)
    events = await fetch_events(entity_id, start, end)

    # One district's teams can be split across Arbiter entities (Pennsauken's
    # high-school entity carries most of Phifer Middle's teams); see
    # arbiter.games_for_school. Only siblings with their own Arbiter scan count.
    siblings = []
    if school.district_id and school.school_type in ("middle", "high"):
        siblings = [
            s
            for s in (await db.execute(select(School).where(School.district_id == school.district_id, School.id != school.id))).scalars().all()
            if entity_id_from_athletics_url(s.athletics_url)
        ]
    sibling_hs_events: list[dict] = []
    if school.school_type == "middle":
        for hs_entity in {entity_id_from_athletics_url(s.athletics_url) for s in siblings if s.school_type == "high"} - {entity_id}:
            sibling_hs_events += [e for e in await fetch_events(hs_entity, start, end) if e.get("kind") != "event"]
    # Cancelled / postponed / rained-out games, from the school calendar page
    # (the feed above has no status). Sibling entities' games come with theirs.
    status_entities = {entity_id}
    if school.school_type == "middle":
        status_entities |= {entity_id_from_athletics_url(s.athletics_url) for s in siblings if s.school_type == "high"}
    statuses: dict[str, str] = {}
    for status_entity in status_entities:
        statuses.update(await fetch_statuses(status_entity, start, end))
    own_uids = {e["external_uid"] for e in events}
    # A middle school pointed at its high school's own entity (Clayton) has
    # only the entity's middle-school teams, not the high school's games.
    if school.school_type == "middle" and any(s.school_type == "high" and entity_id_from_athletics_url(s.athletics_url) == entity_id for s in siblings):
        events = [e for e in events if is_middle_school_team(e)]
    events = games_for_school(school.school_type, events, sibling_hs_events, any(s.school_type == "middle" for s in siblings))
    # Games this school's own entity lists but that now belong to a sibling
    # (stored before the split, or before the sibling was tracked).
    handed_off = own_uids - {e["external_uid"] for e in events}
    if handed_off:
        await db.execute(
            delete(SchoolContentItem).where(
                SchoolContentItem.school_id == school_id,
                SchoolContentItem.source == "arbiter_athletics",
                SchoolContentItem.external_uid.in_(handed_off),
            )
        )
    # Before events had their own id, they were stored under a made-up one
    # ("20261001-Field trip-None"), as hidden games. Real game ids are numeric.
    await db.execute(
        delete(SchoolContentItem).where(
            SchoolContentItem.school_id == school_id,
            SchoolContentItem.source == "arbiter_athletics",
            SchoolContentItem.external_uid.op("~")(r"^\d{8}-"),
        )
    )
    for event in events:
        status = statuses.get(event["external_uid"])
        if status:
            event["title"] = f"{status.upper()} - {event['title']}"
    if not events:
        return "WARNING[no_arbiter_events]: no games found on ArbiterLive for this school"

    existing_by_uid = {
        row.external_uid: row
        for row in (
            await db.execute(
                select(SchoolContentItem).where(
                    or_(
                        SchoolContentItem.school_id == school_id,
                        # Events kept district-wide for this school's district
                        and_(SchoolContentItem.district_id == school.district_id, SchoolContentItem.source == "arbiter_events")
                        if school.district_id
                        else false(),
                    ),
                    SchoolContentItem.source.in_(_SOURCES),
                    SchoolContentItem.external_uid.is_not(None),
                )
            )
        )
        .scalars()
        .all()
    }

    created = updated = 0
    for event in events:
        row = existing_by_uid.get(event["external_uid"])
        if row:
            row.title = event["title"]
            row.description = event["description"]
            row.start_date = event["start_date"]
            row.end_date = event["end_date"]
            row.is_all_day = event["is_all_day"]
            row.source = _source(event, school)
            for field, value in _placement(event, school).items():
                setattr(row, field, value)
            updated += 1
            continue
        db.add(
            SchoolContentItem(
                **_placement(event, school),
                category="event",
                title=event["title"],
                description=event["description"],
                start_date=event["start_date"],
                end_date=event["end_date"],
                is_all_day=event["is_all_day"],
                source=_source(event, school),
                external_uid=event["external_uid"],
            )
        )
        created += 1

    return f"athletics calendar: {created} new, {updated} updated, {len(events)} total"
