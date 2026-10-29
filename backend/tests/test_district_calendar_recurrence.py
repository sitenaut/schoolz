import httpx
import pytest

from services import district_calendar

ICS = b"""BEGIN:VCALENDAR
VERSION:2.0
BEGIN:VEVENT
UID:series1@google.com
DTSTART;TZID=America/New_York:20260916T183000
RRULE:FREQ=MONTHLY;BYDAY=3WE
SUMMARY:B.O.E Meeting
END:VEVENT
BEGIN:VEVENT
UID:series1@google.com
RECURRENCE-ID;TZID=America/New_York:20261021T183000
DTSTART;TZID=America/New_York:20261014T183000
SUMMARY:B.O.E Meeting
END:VEVENT
END:VCALENDAR
"""


@pytest.mark.anyio
async def test_moved_instance_gets_its_own_uid(monkeypatch):
    """A RECURRENCE-ID override shares its series' UID; keyed on that alone
    the scan stored the meeting twice."""

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return httpx.Response(200, content=ICS, request=httpx.Request("GET", url))

    monkeypatch.setattr(district_calendar.httpx, "AsyncClient", FakeClient)
    # Dated 2026; keep its first occurrence inside the stored window whenever this runs.
    monkeypatch.setattr(district_calendar, "_RECUR_PAST", district_calendar._RECUR_PAST * 40)
    events = await district_calendar.fetch_district_calendar("https://example.org/basic.ics")
    uids = [e["external_uid"] for e in events]
    assert len(uids) == len(set(uids))
    assert "series1@google.com" in uids
    # The series is expanded, and the moved instance stands in for the
    # occurrence it replaces rather than showing beside it.
    starts = {e["start_date"].date().isoformat() for e in events}
    assert "2026-10-14" in starts and "2026-10-21" not in starts and "2026-11-18" in starts
    assert all(e["start_date"].hour == 18 and e["start_date"].minute == 30 for e in events)


@pytest.mark.anyio
async def test_smart_sites_generated_feed_is_keyed_on_title_and_start(monkeypatch):
    """Palmyra's generateCalendarICS.php mints new UIDs on every rebuild."""
    builds = iter(["6a1f00aa11", "6a1f99bb22"])

    class FakeClient:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            body = (
                "BEGIN:VCALENDAR\nVERSION:2.0\nBEGIN:VEVENT\nUID:" + next(builds) + "\n"
                "DTSTART;VALUE=DATE:20261224\nSUMMARY:CLOSED - Winter Break\nEND:VEVENT\nEND:VCALENDAR\n"
            )
            return httpx.Response(200, content=body.encode(), request=httpx.Request("GET", url))

    monkeypatch.setattr(district_calendar.httpx, "AsyncClient", FakeClient)
    url = "https://www.palmyraschools.com/sndreq/generateCalendarICS.php?calendar_id=139376"
    first = await district_calendar.fetch_district_calendar(url)
    second = await district_calendar.fetch_district_calendar(url)
    assert first[0]["external_uid"] == second[0]["external_uid"]
    assert first[0]["external_uid"].startswith("hash:")
