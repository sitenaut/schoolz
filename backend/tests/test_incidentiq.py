import asyncio
import html
import json

from services import district_calendar, incidentiq

FEED = "https://pinehill.incidentiq.com/api/event/events?ViewId=aad03058-ad68-f011-8dca-000d3a0dbd19"


def _page(events):
    return f'<input type="hidden" id="eventData" value="{html.escape(json.dumps(events))}" />'


def test_feed_key_detection():
    assert incidentiq.is_incidentiq_feed(FEED)
    assert not incidentiq.is_incidentiq_feed("https://x.org/fs/calendar-manager/events.ics?feed_id=1")


def test_parse_events_reads_rooms_and_naive_times_as_eastern():
    room = {"LocationName": "Bean Elementary", "NameFormatted": "Room 19"}
    events = [
        {"title": "PTO Meeting", "start": "2026-10-07T18:00:00", "end": "2026-10-07T19:00:00", "locationRooms": [room]},
        {"title": "Half Day", "start": "2026-10-09T00:00:00", "end": "2026-10-10T00:00:00", "locationRooms": []},
        {"title": "no start"},
    ]
    out = incidentiq.parse_events(_page(events))
    assert [e["title"] for e in out] == ["PTO Meeting", "Half Day"]
    assert out[0]["start_date"].utcoffset().total_seconds() == -4 * 3600
    assert out[0]["description"] == "Location: Bean Elementary - Room 19"
    assert not out[0]["is_all_day"] and out[1]["is_all_day"]


def test_same_event_in_two_rooms_gets_two_uids_and_is_stable():
    base = {"title": "Concert", "start": "2026-10-07T18:00:00"}
    a = {**base, "locationRooms": [{"LocationName": "OHS", "Name": "Gym"}]}
    b = {**base, "locationRooms": [{"LocationName": "OHS", "Name": "Cafeteria"}]}
    uids = [e["external_uid"] for e in incidentiq.parse_events(_page([a, b]))]
    assert len(set(uids)) == 2
    assert uids == [e["external_uid"] for e in incidentiq.parse_events(_page([a, b]))]


def test_district_calendar_routes_feed_key_to_adapter(monkeypatch):
    async def fake(url, timeout):
        return [{"title": "x"}]

    monkeypatch.setattr(incidentiq, "fetch_events", fake)
    assert asyncio.run(district_calendar.fetch_district_calendar(FEED)) == [{"title": "x"}]
