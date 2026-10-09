import re
from datetime import datetime, timezone
from pathlib import Path

import pytest

from local_events.prune import SOURCE_KEYS
from local_events.sources.placewise import parse_events

FIXTURE = Path(__file__).parent / "fixtures" / "placewise_promenade_events.html"
URL = "https://thepromenadenj.com/events"


def _parse():
    return parse_events(
        FIXTURE.read_text(),
        URL,
        "promenade_sagemore",
        venue_name="The Promenade at Sagemore",
        venue_address="500 Route 73 S, Marlton, NJ 08053",
        default_categories=["marlton"],
    )


def test_timed_events_keep_their_instants_and_ranges_are_all_day():
    by_title = {e.title: e for e in _parse()}
    truck = by_title["Touch a Truck"]
    assert truck.start_time == datetime(2026, 10, 3, 14, 0, tzinfo=timezone.utc)
    assert truck.end_time == datetime(2026, 10, 3, 18, 0, tzinfo=timezone.utc)
    assert not truck.all_day
    assert truck.url == "https://thepromenadenj.com/event/42350-touch-a-truck-26"
    assert truck.venue_name == "The Promenade at Sagemore" and truck.venue_address.startswith("500 Route 73 S")

    scarecrow = by_title["Scarecrow Contest"]
    assert scarecrow.all_day and scarecrow.start_time.date().isoformat() == "2026-10-17"
    assert scarecrow.end_time.date().isoformat() == "2026-10-31"
    assert "Youth groups are invited" in scarecrow.description and "<p>" not in scarecrow.description
    assert scarecrow.default_categories == ["marlton"] and scarecrow.source_event_id == "43260"


def test_open_ended_store_promotions_are_skipped_and_store_events_name_the_store():
    events = {e.title: e for e in _parse()}
    # "NEW YEAR, NEW JEANS" is a Madewell sale running since January with no end date.
    assert "NEW YEAR, NEW JEANS" not in events
    assert events["Home Services Industry Night"].venue_name == "California Closets at The Promenade at Sagemore"
    assert len(events) == 3


def test_a_page_without_the_events_container_raises_instead_of_returning_nothing():
    with pytest.raises(ValueError):
        parse_events("<html><body>redesigned</body></html>", URL, "x")
    with pytest.raises(ValueError):
        parse_events('<script id="__NEXT_DATA__" type="application/json">{"props": {}}</script>', URL, "x")


def test_prune_knows_every_source_list_the_pipeline_reads():
    # A key missing here makes every job edit delete that source's events as "orphaned".
    pipeline = (Path(__file__).parent.parent / "local_events" / "pipeline.py").read_text()
    read = set(re.findall(r'params\.get\("(\w+_sources)"\)', pipeline))
    assert read and read <= set(SOURCE_KEYS), sorted(read - set(SOURCE_KEYS))


@pytest.mark.anyio
async def test_prune_never_deletes_events_published_from_community_submissions():
    import uuid
    from datetime import datetime, timezone

    import database
    from local_events.prune import COMMUNITY_SOURCE, prune_orphaned_events
    from models import LocalEvent
    from sqlalchemy import select

    async with database.SessionLocal() as db:
        keep = LocalEvent(source=COMMUNITY_SOURCE, source_event_id=uuid.uuid4().hex, title="Kept", start_time=datetime.now(timezone.utc), categories=[])
        orphan = LocalEvent(source="gone-feed", source_event_id=uuid.uuid4().hex, title="Orphan", start_time=datetime.now(timezone.utc), categories=[])
        db.add_all([keep, orphan])
        await db.flush()
        await prune_orphaned_events(db)
        remaining = {r for r in (await db.execute(select(LocalEvent.title).where(LocalEvent.id.in_([keep.id, orphan.id])))).scalars()}
    assert remaining == {"Kept"}
