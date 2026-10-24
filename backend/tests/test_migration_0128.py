"""The 0128 backfill, run against rows in the test transaction."""
import importlib.util
import uuid
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import pytest
import sqlalchemy as sa

import database
from models import District, SchoolContentItem

ET = ZoneInfo("America/New_York")
_PATH = Path(__file__).resolve().parent.parent / "alembic" / "versions" / "0128_all_day_end_day_after.py"


def _migration():
    spec = importlib.util.spec_from_file_location("migration_0128", _PATH)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.mark.anyio
async def test_only_model_read_multi_day_ranges_move_and_only_once():
    m = _migration()
    statement = sa.text(m.FIX_SQL).bindparams(sa.bindparam("sources", expanding=True))
    async with database.SessionLocal() as db:
        district = District(name=f"Backfill District {uuid.uuid4().hex[:8]}")
        db.add(district)
        await db.flush()

        def row(source: str, start_day: int, end_day: int | None, all_day: bool = True) -> SchoolContentItem:
            item = SchoolContentItem(
                scope="district", district_id=district.id, category="event", title=f"{source} {start_day}-{end_day}",
                start_date=datetime(2026, 11, start_day, tzinfo=ET),
                end_date=datetime(2026, 11, end_day, 0 if all_day else 21, tzinfo=ET) if end_day else None,
                is_all_day=all_day, source=source,
            )
            db.add(item)
            return item

        njea = row("newsletter", 5, 6)  # printed "Nov 5-6"
        portraits = row("hs_activities_site", 12, 15)
        feed = row("ics_feed", 5, 7)  # already the day after
        one_day = row("newsletter", 9, 9)
        timed = row("community", 5, 6, all_day=False)
        no_end = row("givebacks_pta", 5, None)
        await db.flush()
        ids = [r.id for r in (njea, portraits, feed, one_day, timed, no_end)]

        await db.execute(statement, {"sources": list(m.SOURCES)})
        ends = {
            r.id: r.end_date
            for r in (await db.execute(sa.select(SchoolContentItem).where(SchoolContentItem.id.in_(ids)).execution_options(populate_existing=True))).scalars()
        }

    def day(d):
        return d.astimezone(ET).date().isoformat() if d else None

    assert day(ends[njea.id]) == "2026-11-07" and ends[njea.id].astimezone(ET).hour == 0
    assert day(ends[portraits.id]) == "2026-11-16"
    assert day(ends[feed.id]) == "2026-11-07"  # not a model-fed source
    assert day(ends[one_day.id]) == "2026-11-09"
    assert ends[timed.id].astimezone(ET).hour == 21  # timed, not all-day
    assert ends[no_end.id] is None
