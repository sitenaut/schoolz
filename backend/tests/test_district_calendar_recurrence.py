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
    events = await district_calendar.fetch_district_calendar("https://example.org/basic.ics")
    uids = [e["external_uid"] for e in events]
    assert len(uids) == 2 and len(set(uids)) == 2
    assert "series1@google.com" in uids
