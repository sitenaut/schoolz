"""Bug sweep 2026-10-23 lows in ingest: half-done translations, tool output
read without its shape guard, a district's menu job, the announcements
watermark, recurring feed events, model-chosen supersedes and a seed slug."""
import json
import os
import uuid
from datetime import UTC, date, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import httpx
import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import ContentTranslation, School, SchoolContentItem
from services import content_translation as ct
from services import district_calendar, district_calendar_pdf, hs_announcements, lunch_menu, special_events
from tests.test_admin_config import _district, _make_admin, _school, _unique

pytestmark = pytest.mark.anyio


def _fake_model(module, monkeypatch, tool_input, stop_reason="tool_use"):
    class _Messages:
        async def create(self, **kwargs):
            blocks = [SimpleNamespace(type="tool_use", input=tool_input)] if tool_input is not None else []
            return SimpleNamespace(content=blocks, stop_reason=stop_reason, usage=None)

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(module, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(module, "AsyncAnthropic", _Client)
    monkeypatch.setattr(module.observability, "record_llm_call", lambda *a, **k: None)


async def _admin(client: AsyncClient) -> dict:
    email = f"ingest_{uuid.uuid4().hex[:8]}@example.com"
    reg = await client.post("/auth/register", json={"email": email, "username": _unique("ingest"), "password": "password123"})
    await _make_admin(email)
    return {"authorization": f"Bearer {reg.json()['access_token']}"}


# ---- F33: a translation that lost its description --------------------------


async def test_a_translation_without_its_description_is_not_stored(monkeypatch):
    async def model(payload, lang, guidance=""):
        return {0: ("Salida temprana", None), 1: ("Día de fotos", None)}

    monkeypatch.setattr(ct, "_call_model", model)
    got = await ct._translate_chunk([("a", "Early dismissal", "Buses run 2 hours early"), ("b", "Picture day", None)], "es")
    assert got == {"b": ("Día de fotos", None)}


async def test_a_stored_half_translation_is_served_in_english_and_redone(monkeypatch):
    queued = []
    monkeypatch.setattr(ct, "_queue", lambda items, lang: queued.extend(i.id for i in items))
    start = datetime.now(UTC) + timedelta(days=3)
    async with database.SessionLocal() as db:
        school = School(name=f"Translate School {uuid.uuid4().hex[:6]}", slug=f"tr-{uuid.uuid4().hex[:8]}")
        db.add(school)
        await db.flush()
        item = SchoolContentItem(
            scope="school", school_id=school.id, category="reminder", title="Early dismissal",
            description="Buses run 2 hours early", start_date=start,
        )
        db.add(item)
        await db.flush()
        db.add(ContentTranslation(
            item_id=item.id, lang="es", title="Salida temprana", description=None,
            source_hash=ct.source_hash(item.title, item.description), model="m", created_at=datetime.now(UTC),
        ))
        await db.commit()
        loc = (await ct.apply_translations(db, [item], "es"))[item.id]
        assert (loc.title, loc.description, loc.translated) == ("Early dismissal", "Buses run 2 hours early", False)
        assert queued == [item.id]
        # Nor is it copied to another item with the same text.
        twin = SchoolContentItem(
            scope="school", school_id=school.id, category="reminder", title=item.title,
            description=item.description, start_date=start,
        )
        db.add(twin)
        await db.flush()
        assert await ct._reuse_by_hash(db, [twin], "es") == set()


# ---- F36: tool output as a JSON string -------------------------------------


async def test_menu_days_sent_as_a_json_string_are_still_read(monkeypatch):
    days = json.dumps([{"date": "2026-10-05", "description": "Chicken tenders"}])
    _fake_model(lunch_menu, monkeypatch, {"days": days})

    async def fake_bytes(url, **kwargs):
        return "application/pdf", b"%PDF-1.4"

    monkeypatch.setattr(lunch_menu.scraper_client, "get_bytes", fake_bytes)
    items = await lunch_menu.parse_menu_pdf("https://example.org/oct-lunch.pdf", "October 2026")
    assert [(i["date"].day, i["description"]) for i in items] == [(5, "Chicken tenders")]


async def test_special_events_sent_as_a_json_string_are_still_read(monkeypatch):
    _fake_model(special_events, monkeypatch, {"items": json.dumps([{"day": 21, "title": "Pajama Day"}])})

    async def fake_bytes(url, **kwargs):
        return "application/pdf", b"%PDF-1.4"

    monkeypatch.setattr(special_events.scraper_client, "get_bytes", fake_bytes)
    items = await special_events.parse_special_events_pdf("https://example.org/oct-events.pdf", 2026, 10)
    assert [(i["date"].day, i["title"]) for i in items] == [(21, "Pajama Day")]


async def test_calendar_pdf_events_as_a_string_are_read_and_junk_keeps_the_stored_rows(monkeypatch):
    events = [{"date": "2026-09-07", "kind": "closed", "subject": "Labor Day"}]
    _fake_model(district_calendar_pdf, monkeypatch, {"events": json.dumps(events)})
    assert await district_calendar_pdf.extract_events(b"%PDF-1.4") == events

    _fake_model(district_calendar_pdf, monkeypatch, {"events": [events[0], "not an event"]})
    with pytest.raises(RuntimeError):
        await district_calendar_pdf.extract_events(b"%PDF-1.4")


# ---- F39: a district that gains a menu URL by PATCH -------------------------


async def test_patching_in_a_menu_url_creates_the_menu_scan_job():
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        district = await client.post("/districts", json={"name": f"Menu District {uuid.uuid4().hex[:6]}"}, headers=headers)
        assert district.status_code == 201, district.text
        assert district.json()["scheduled_job"] is None
        patched = await client.patch(
            f"/districts/{district.json()['id']}", json={"food_services_menu_url": "https://example.org/menus"}, headers=headers
        )
        assert patched.status_code == 200, patched.text
        assert patched.json()["scheduled_job"]["kind"] == "lunch_menu.scan"


# ---- F55: the announcements watermark --------------------------------------


async def test_a_day_block_the_model_skipped_is_read_again_next_run(monkeypatch):
    doc = "Monday, October 19, 2026\n* Chess club meets in 204\nTuesday, October 20, 2026\n* No late buses today\n"

    class _Doc:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return httpx.Response(200, text=doc, request=httpx.Request("GET", url))

    calls = []

    class _Messages:
        async def create(self, **kwargs):
            calls.append(kwargs["messages"][0]["content"])
            if "late buses" in kwargs["messages"][0]["content"]:
                return SimpleNamespace(content=[], stop_reason="end_turn", usage=None)
            items = {"items": [{"title": "Chess club", "kind": "meeting", "start_date": "2026-10-19"}]}
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input=items)], stop_reason="tool_use", usage=None)

    monkeypatch.setattr(hs_announcements.httpx, "AsyncClient", _Doc)
    monkeypatch.setattr(hs_announcements, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(hs_announcements, "AsyncAnthropic", lambda **k: SimpleNamespace(messages=_Messages()))
    monkeypatch.setattr(hs_announcements.observability, "record_llm_call", lambda *a, **k: None)

    async with database.SessionLocal() as db:
        school = School(
            name=f"Announce High {uuid.uuid4().hex[:6]}", slug=f"ann-{uuid.uuid4().hex[:8]}", school_type="high",
            announcements_doc_url="https://docs.google.com/document/d/abc/edit",
        )
        db.add(school)
        await db.flush()
        result = await hs_announcements.scan_announcements(db, school)
        assert result.startswith("WARNING[incomplete_day_block]") and "2026-10-20" in result
        assert school.announcements_last_parsed_date == "2026-10-19"

        calls.clear()
        await hs_announcements.scan_announcements(db, school)
        assert len(calls) == 1 and "late buses" in calls[0]


# ---- F56: recurring district feed events ------------------------------------


async def _feed(monkeypatch, ics: bytes) -> list[dict]:
    class _Client:
        def __init__(self, *a, **k):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *a):
            return False

        async def get(self, url, headers=None):
            return httpx.Response(200, content=ics, request=httpx.Request("GET", url))

    monkeypatch.setattr(district_calendar.httpx, "AsyncClient", _Client)
    return await district_calendar.fetch_district_calendar("https://example.org/district.ics")


def _ics(*events: str) -> bytes:
    return ("BEGIN:VCALENDAR\r\nVERSION:2.0\r\n" + "".join(events) + "END:VCALENDAR\r\n").encode()


def _first_wednesday_from_now() -> date:
    d = date.today() + timedelta(days=7)
    return d + timedelta(days=(2 - d.weekday()) % 7)


async def test_a_weekly_all_day_series_shows_every_week_except_its_exdates(monkeypatch):
    first = _first_wednesday_from_now()
    skip = first + timedelta(days=7)
    until = first + timedelta(days=21)
    events = await _feed(monkeypatch, _ics(
        "BEGIN:VEVENT\r\nUID:wed@district\r\n"
        f"DTSTART;VALUE=DATE:{first:%Y%m%d}\r\nDTEND;VALUE=DATE:{first + timedelta(days=1):%Y%m%d}\r\n"
        f"RRULE:FREQ=WEEKLY;BYDAY=WE;UNTIL={until:%Y%m%d}T235959Z\r\n"
        f"EXDATE;VALUE=DATE:{skip:%Y%m%d}\r\n"
        "SUMMARY:Early Dismissal\r\nEND:VEVENT\r\n"
    ))
    days = [e["start_date"].date() for e in events]
    assert days == [first, first + timedelta(days=14), until]
    assert events[0]["external_uid"] == "wed@district"
    assert len({e["external_uid"] for e in events}) == 3
    assert all(e["is_all_day"] and (e["end_date"] - e["start_date"]).days == 1 for e in events)


async def test_a_moved_or_cancelled_instance_replaces_its_occurrence(monkeypatch):
    first = _first_wednesday_from_now()
    moved_from, cancelled = first + timedelta(days=7), first + timedelta(days=14)
    events = await _feed(monkeypatch, _ics(
        "BEGIN:VEVENT\r\nUID:boe@district\r\n"
        f"DTSTART;TZID=America/New_York:{first:%Y%m%d}T183000\r\nRRULE:FREQ=WEEKLY;COUNT=4\r\n"
        "SUMMARY:Board Meeting\r\nEND:VEVENT\r\n",
        "BEGIN:VEVENT\r\nUID:boe@district\r\n"
        f"RECURRENCE-ID;TZID=America/New_York:{moved_from:%Y%m%d}T183000\r\n"
        f"DTSTART;TZID=America/New_York:{moved_from + timedelta(days=1):%Y%m%d}T183000\r\n"
        "SUMMARY:Board Meeting\r\nEND:VEVENT\r\n",
        "BEGIN:VEVENT\r\nUID:boe@district\r\n"
        f"RECURRENCE-ID;TZID=America/New_York:{cancelled:%Y%m%d}T183000\r\n"
        f"DTSTART;TZID=America/New_York:{cancelled:%Y%m%d}T183000\r\nSTATUS:CANCELLED\r\n"
        "SUMMARY:Board Meeting\r\nEND:VEVENT\r\n",
        "BEGIN:VEVENT\r\nUID:gone@district\r\nDTSTART;VALUE=DATE:20261201\r\nSTATUS:CANCELLED\r\n"
        "SUMMARY:Concert\r\nEND:VEVENT\r\n",
    ))
    days = sorted(e["start_date"].date() for e in events)
    assert days == [first, moved_from + timedelta(days=1), first + timedelta(days=21)]
    assert all(e["start_date"].hour == 18 for e in events)


# ---- F57: a supersede must name one of the school's own items ---------------


async def test_a_supersede_naming_another_schools_item_is_ignored():
    from services.content_extractor import apply_supersede

    soon = datetime.now(UTC) + timedelta(days=10)
    async with database.SessionLocal() as db:
        mine = School(name=f"Mine {uuid.uuid4().hex[:6]}", slug=f"mine-{uuid.uuid4().hex[:8]}")
        theirs = School(name=f"Theirs {uuid.uuid4().hex[:6]}", slug=f"theirs-{uuid.uuid4().hex[:8]}")
        db.add_all([mine, theirs])
        await db.flush()
        rows = {
            name: SchoolContentItem(scope="school", school_id=school.id, category="event", title=name, start_date=soon, source=source)
            for name, school, source in [
                ("theirs", theirs, None), ("own", mine, None), ("own pta", mine, "givebacks_pta"), ("new", mine, None),
            ]
        }
        db.add_all(rows.values())
        await db.flush()
        new = rows["new"]

        assert not await apply_supersede(db, rows["theirs"].id, new, school_id=mine.id)
        assert not await apply_supersede(db, rows["own"].id, new, school_id=mine.id, source="givebacks_pta")
        assert await apply_supersede(db, rows["own pta"].id, new, school_id=mine.id, source="givebacks_pta")
        assert await apply_supersede(db, rows["own"].id, new, school_id=mine.id)
        assert rows["theirs"].is_current and not rows["own"].is_current and rows["own"].superseded_by_id == new.id


# ---- F59: a seed school matched by name, under another slug -----------------


async def test_a_school_matched_by_name_keeps_its_seed_newsletters():
    run = uuid.uuid4().hex[:8]
    district_name = f"Slug District {run}"
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        headers = await _admin(client)
        first = {"exported_at": "2026-01-01T00:00:00Z", "source": "test", "districts": [_district(district_name)],
                 "schools": [_school(f"x-{run}", f"Slug School {run}", district_name)], "smore_newsletters": []}
        assert (await client.post("/admin/config/import", json=first, headers=headers)).status_code == 200

        url = f"https://app.smore.com/n/slug-{run}"
        second = {**first, "schools": [_school(f"x-elementary-{run}", f"Slug School {run}", district_name)],
                  "smore_newsletters": [{"url": url, "label": "News", "school_slug": f"x-elementary-{run}",
                                         "cron_expr": "0 8 * * 1", "timezone": "America/New_York", "enabled": True}]}
        res = await client.post("/admin/config/import", json=second, headers=headers)
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["schools_updated"] == 1 and body["smore_skipped"] == [] and body["smore_created"] == 1
