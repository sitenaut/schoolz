"""/local's grid dots (GET /local-events/days) and its light list rows
(GET /local-events/rows): a day's dot counts exactly the events its list
shows, by the same rule the page files rows under days."""
import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import date, datetime
from zoneinfo import ZoneInfo

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import LocalEvent
from routers.local_events import date_keys

pytestmark = pytest.mark.anyio

ET = ZoneInfo("America/New_York")


def et(y, m, d, h=0, mi=0):
    return datetime(y, m, d, h, mi, tzinfo=ET)


def test_date_keys_follow_the_pages_rule():
    # frontend/src/lib/calendar.ts:itemDateKeys, case by case.
    assert date_keys(et(2031, 3, 4, 10), None, False) == [date(2031, 3, 4)]
    # 9pm Eastern is the next day in UTC; the date is Cherry Hill's.
    assert date_keys(et(2031, 3, 4, 21), et(2031, 3, 4, 22), False) == [date(2031, 3, 4)]
    # All-day ends are exclusive: Nov 5 - Nov 7 covers the 5th and 6th.
    assert date_keys(et(2031, 11, 5), et(2031, 11, 7), True) == [date(2031, 11, 5), date(2031, 11, 6)]
    assert date_keys(et(2031, 11, 5), et(2031, 11, 6), True) == [date(2031, 11, 5)]
    # A timed end on a later date counts that date, midnight included.
    assert date_keys(et(2031, 3, 4, 22), et(2031, 3, 5, 0), False) == [date(2031, 3, 4), date(2031, 3, 5)]


async def _events(src: str) -> None:
    async with database.SessionLocal() as db:
        db.add_all(
            [
                LocalEvent(source=src, source_event_id="a", title="Story Time", description="Long text " * 50, start_time=et(2031, 3, 4, 10), venue_name="Library"),
                LocalEvent(source=src, source_event_id="b", title="Late Show", start_time=et(2031, 3, 4, 22), end_time=et(2031, 3, 5, 0)),
                LocalEvent(source=src, source_event_id="c", title="Art Week", start_time=et(2031, 3, 2), end_time=et(2031, 3, 7), all_day=True),
                LocalEvent(source=src, source_event_id="d", title="Ends Before", start_time=et(2031, 3, 3), end_time=et(2031, 3, 4), all_day=True),
                LocalEvent(source=src, source_event_id="e", title="Next Month", start_time=et(2031, 4, 2, 9)),
            ]
        )
        await db.commit()


async def test_days_count_each_date_an_event_covers_inside_the_range():
    src = f"days_{uuid.uuid4().hex[:8]}"
    await _events(src)
    march = {"start": et(2031, 3, 1).isoformat(), "end": et(2031, 3, 31, 23, 59).isoformat(), "source": src}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = (await client.get("/local-events/days", params=march)).json()
        assert res["total"] == 4
        assert res["days"] == {"2031-03-02": 1, "2031-03-03": 2, "2031-03-04": 3, "2031-03-05": 2, "2031-03-06": 1}

        free = (await client.get("/local-events/days", params={**march, "q": "story"})).json()
        assert free["days"] == {"2031-03-04": 1}

        too_wide = await client.get("/local-events/days", params={"start": "2031-01-01T00:00:00Z", "end": "2032-03-01T00:00:00Z"})
        assert too_wide.status_code == 422


async def test_a_days_rows_are_exactly_what_its_dot_counts_and_carry_no_description():
    src = f"rows_{uuid.uuid4().hex[:8]}"
    await _events(src)
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = (await client.get("/local-events/rows", params={"day": "2031-03-04", "source": src})).json()
        # The all-day event ending (exclusively) on the 4th is not on it.
        assert [r["title"] for r in res["items"]] == ["Art Week", "Story Time", "Late Show"] and res["total"] == 3
        assert "description" not in res["items"][0] and res["items"][1]["venue_name"] == "Library"
        nxt = (await client.get("/local-events/rows", params={"day": "2031-03-05", "source": src})).json()
        assert [r["title"] for r in nxt["items"]] == ["Art Week", "Late Show"]  # the show ending at midnight

        march = {"start": et(2031, 3, 1).isoformat(), "end": et(2031, 3, 31, 23, 59).isoformat(), "source": src}
        page = (await client.get("/local-events/rows", params={**march, "limit": 2, "offset": 1})).json()
        assert page["total"] == 4 and [r["title"] for r in page["items"]] == ["Ends Before", "Story Time"]

        # The sheet still gets the whole event by id.
        full = (await client.get(f"/local-events/{res['items'][1]['id']}")).json()
        assert full["description"].startswith("Long text")
