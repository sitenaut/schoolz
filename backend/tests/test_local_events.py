import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import json
from datetime import datetime, timezone
from unittest.mock import patch

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select

import database
from local_events.billz_import import plan_import
from local_events.sources.base import RawEvent, Source
from main import app
from models import LocalEvent, ScheduledJob
from scheduler.jobs import local_events_refresh
from tests.test_students import _make_admin, _register

pytestmark = pytest.mark.anyio


def auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _utc(*a):
    return datetime(*a, tzinfo=timezone.utc)


# ---- billz import -------------------------------------------------------------


def test_plan_import_accepts_params_job_and_job_list():
    params = {"ical_sources": [{"name": "lib", "url": "https://x/cal.ics"}]}
    [job], skipped = plan_import(json.dumps(params))
    assert job["kind"] == "local_events.refresh" and job["params"] == params and not skipped

    billz_job = {"kind": "events.refresh", "name": "Local events", "cron_expr": "0 */3 * * *", "timezone": "America/New_York", "enabled": False, "params": params}
    plaid = {"kind": "plaid.sync", "name": "Plaid", "cron_expr": "0 * * * *", "params": {}}
    jobs, skipped = plan_import(json.dumps([billz_job, plaid]))
    assert [(j["name"], j["cron_expr"], j["enabled"]) for j in jobs] == [("Local events", "0 */3 * * *", False)]
    assert skipped == [{"name": "Plaid", "reason": "kind 'plaid.sync' has no schoolz equivalent"}]

    with pytest.raises(ValueError):
        plan_import("{not json")


async def test_import_endpoint_is_admin_only_and_idempotent():
    run = uuid.uuid4().hex[:8]
    params = {"rss_sources": [{"name": f"feed-{run}", "url": f"https://example.com/{run}.xml"}]}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _register(client, f"imp_{run}@example.com", f"imp_{run}")
        user = await _register(client, f"u_{run}@example.com", f"u_{run}")
        await _make_admin(f"imp_{run}@example.com")
        body = {"text": json.dumps({"kind": "events.refresh", "name": f"billz {run}", "cron_expr": "0 */3 * * *", "params": params})}
        assert (await client.post("/scheduled-jobs/import-billz", json=body, headers=auth(user))).status_code == 403
        first = (await client.post("/scheduled-jobs/import-billz", json=body, headers=auth(admin))).json()
        assert [j["name"] for j in first["created"]] == [f"billz {run}"]
        second = (await client.post("/scheduled-jobs/import-billz", json=body, headers=auth(admin))).json()
        assert second["created"] == [] and second["skipped"][0]["reason"].startswith("same sources")
        bad = await client.post("/scheduled-jobs/import-billz", json={"text": "nope"}, headers=auth(admin))
        assert bad.status_code == 400


# ---- pipeline + job ------------------------------------------------------------


class _FakeSource(Source):
    def __init__(self, name, events=None, fail=False):
        self.name = name
        self._events = events or []
        self._fail = fail

    async def fetch(self):
        if self._fail:
            raise RuntimeError("boom")
        return self._events


def _raw(source, sid, title, start, venue="Cherry Hill Library", **kw):
    return RawEvent(source=source, source_event_id=sid, title=title, start_time=start, venue_name=venue, **kw)


async def test_refresh_upserts_dedupes_across_sources_and_warns_on_failure():
    run = uuid.uuid4().hex[:8]
    a, b = f"src_a_{run}", f"src_b_{run}"
    start = _utc(2031, 5, 3, 15)
    sources = [
        _FakeSource(a, [_raw(a, "1", f"Story Time {run}", start, description="short")]),
        # Same event from a second feed, 10 minutes off, longer description.
        _FakeSource(b, [_raw(b, "x", f"Story Time {run}", start.replace(minute=10), description="a much longer description")]),
        _FakeSource(f"dead_{run}", fail=True),
    ]
    async with database.SessionLocal() as db:
        with patch("local_events.pipeline._build_sources", return_value=sources):
            result = await local_events_refresh.run(db, {})
            again = await local_events_refresh.run(db, {})
        rows = (await db.execute(select(LocalEvent).where(LocalEvent.title == f"Story Time {run}"))).scalars().all()
    assert result.startswith("WARNING[local_event_source_failed]") and f"dead_{run}" in result
    assert again.startswith("WARNING")
    [row] = rows
    assert row.source == a and row.description == "a much longer description"
    assert "library" in row.categories and "kids" not in row.categories


async def test_seeded_refresh_job_exists():
    async with database.SessionLocal() as db:
        job = (await db.execute(select(ScheduledJob).where(ScheduledJob.kind == "local_events.refresh"))).scalars().first()
    assert job is not None and "evvnt_sources" in job.params and job.params["gcal_sources"] == []


# ---- read API ------------------------------------------------------------------


async def test_local_events_api_requires_login_and_filters():
    run = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        db.add_all(
            [
                LocalEvent(source=f"s1_{run}", source_event_id="1", title=f"Free concert {run}", start_time=_utc(2031, 6, 1, 23), is_free=True, categories=["music", "free"], venue_name="Croft Farm"),
                LocalEvent(source=f"s1_{run}", source_event_id="2", title=f"Paid play {run}", start_time=_utc(2031, 6, 2, 23), is_free=False, categories=["arts"]),
                LocalEvent(source=f"s2_{run}", source_event_id="3", title=f"July fair {run}", start_time=_utc(2031, 7, 4, 16), categories=["outdoor"]),
            ]
        )
        await db.commit()
    rng = {"start": "2031-06-01T04:00:00Z", "end": "2031-07-01T03:59:59Z"}
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        assert (await client.get("/local-events", params=rng)).status_code == 401
        token = await _register(client, f"le_{run}@example.com", f"le_{run}")

        async def titles(**extra):
            res = await client.get("/local-events", params={**rng, "q": run, **extra}, headers=auth(token))
            assert res.status_code == 200, res.text
            return {i["title"] for i in res.json()["items"]}

        assert await titles() == {f"Free concert {run}", f"Paid play {run}"}
        assert await titles(is_free="true") == {f"Free concert {run}"}
        assert await titles(categories="arts,outdoor") == {f"Paid play {run}"}
        assert await titles(q=f"{run} croft") == {f"Free concert {run}"}
        assert await titles(source=f"s2_{run}") == set()

        facets = (await client.get("/local-events/facets", params=rng, headers=auth(token))).json()
        assert {"value": f"s1_{run}", "count": 2} in facets["sources"]
        assert any(c["value"] == "music" for c in facets["categories"])


def test_dpcalendar_source_adds_a_date_window_unless_the_url_has_one():
    from datetime import date

    from local_events.sources.json_api import JsonApiSource

    base = "https://evesham-nj.org/index.php?option=com_dpcalendar&view=events&format=raw"
    src = JsonApiSource(name="e", url=base, parser="dpcalendar")
    assert src.request_url(date(2026, 9, 22)) == base + "&date-start=2026-09-22&date-end=2026-12-21"
    assert JsonApiSource(name="e", url=base + "&date-start=2026-01-01", parser="dpcalendar").request_url() == base + "&date-start=2026-01-01"
    assert JsonApiSource(name="e", url=base).request_url() == base


async def test_removing_a_source_or_job_removes_its_events_unless_another_job_lists_it():
    run = uuid.uuid4().hex[:8]
    only_a, shared, only_b = f"only_a_{run}", f"shared_{run}", f"only_b_{run}"

    def params(*names):
        return {"ical_sources": [{"name": n, "url": f"https://example.com/{n}.ics"} for n in names]}

    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        admin = await _register(client, f"pr_{run}@example.com", f"pr_{run}")
        await _make_admin(f"pr_{run}@example.com")

        async def create(name, p):
            body = {"kind": "local_events.refresh", "name": name, "cron_expr": "0 */6 * * *", "params": p}
            res = await client.post("/scheduled-jobs", json=body, headers=auth(admin))
            assert res.status_code == 201, res.text
            return res.json()["id"]

        job_a = await create(f"A {run}", params(only_a, shared))
        job_b = await create(f"B {run}", params(shared, only_b))
        async with database.SessionLocal() as db:
            for i, src in enumerate((only_a, shared, only_b)):
                db.add(LocalEvent(source=src, source_event_id=str(i), title=f"{src} event", start_time=_utc(2031, 1, 1 + i, 15)))
            await db.commit()

        async def sources_left():
            async with database.SessionLocal() as db:
                rows = (await db.execute(select(LocalEvent.source).where(LocalEvent.source.in_([only_a, shared, only_b])))).scalars().all()
            return set(rows)

        # Disabling keeps everything.
        assert (await client.patch(f"/scheduled-jobs/{job_a}", json={"enabled": False}, headers=auth(admin))).status_code == 200
        assert await sources_left() == {only_a, shared, only_b}

        # Deleting A drops only_a; shared survives because B still lists it.
        assert (await client.delete(f"/scheduled-jobs/{job_a}", headers=auth(admin))).status_code == 204
        assert await sources_left() == {shared, only_b}

        # Editing B to drop `shared` removes its events too.
        assert (await client.patch(f"/scheduled-jobs/{job_b}", json={"params": params(only_b)}, headers=auth(admin))).status_code == 200
        assert await sources_left() == {only_b}


@pytest.mark.anyio
async def test_gcal_bare_ids_get_group_suffix_and_one_dead_calendar_doesnt_sink_the_rest(monkeypatch):
    from local_events.sources.base import RawEvent
    from local_events.sources.gcal import GoogleCalendarSource

    src = GoogleCalendarSource("phila_gov", ["mayor@gmail.com", "6kfp8odc1an5o5sl874rr3hhck", "dead@gmail.com"], "key")
    assert src.calendar_ids[1] == "6kfp8odc1an5o5sl874rr3hhck@group.calendar.google.com"

    async def fake_fetch(client, cal_id):
        if cal_id == "dead@gmail.com":
            raise RuntimeError("Google Calendar API returned HTTP 404 for calendar 'dead@gmail.com'")
        return [RawEvent(source="phila_gov", source_event_id=cal_id, title=cal_id, start_time=datetime(2031, 6, 1, tzinfo=timezone.utc))]

    monkeypatch.setattr(src, "_fetch_calendar", fake_fetch)
    events = await src.fetch()
    assert len(events) == 2
    assert len(src.partial_failures) == 1 and "dead@gmail.com" in src.partial_failures[0]

    # Every calendar failing is still a failed source.
    only_dead = GoogleCalendarSource("x", ["dead@gmail.com"], "key")
    monkeypatch.setattr(only_dead, "_fetch_calendar", fake_fetch)
    with pytest.raises(RuntimeError):
        await only_dead.fetch()


@pytest.mark.parametrize(
    "title, description, expect, reject",
    [
        # The Philadelphia School's rows: bare instrument titles, "Lessons" only in the description.
        ("Cello", "Lessons will be scheduled on a first-come, first-served basis.", {"classes-&-lessons"}, {"sports", "arts"}),
        ("Intro to Watercolor Class", None, {"classes-&-lessons"}, set()),
        ("CPR Training", None, {"classes-&-lessons"}, {"exercise"}),
        ("Personal Training at the Y", None, {"classes-&-lessons", "exercise"}, set()),
        ("Adult Education Course: Spanish I", None, {"classes-&-lessons"}, set()),
        # Not classes.
        ("A world-class jazz trio", None, set(), {"classes-&-lessons"}),
        ("Class of 2027 Fundraiser", None, set(), {"classes-&-lessons"}),
        ("Golf Course Cleanup", "Of course, all are welcome.", set(), {"classes-&-lessons"}),
        # The old ungrouped alternations: "brace"/"start"/"party"/"sparkle" matched sports/arts/outdoor.
        ("Brace yourself: start of the party season", "Sparkle and shine", set(), {"sports", "arts", "outdoor"}),
        ("Art in the Park", None, {"arts", "outdoor"}, set()),
    ],
)
def test_keyword_categories(title, description, expect, reject):
    from local_events.normalizer import _infer_categories

    cats = set(_infer_categories(title, description, []))
    assert expect <= cats, cats
    assert not (reject & cats), cats


def test_source_class_categories_fold_into_classes_and_lessons():
    from local_events.normalizer import _infer_categories

    assert "classes-&-lessons" in _infer_categories("Pottery", None, ["classes-/-courses"])


@pytest.mark.parametrize(
    "description, is_class",
    [
        ("Lessons will be scheduled on a first-come, first-served basis.", True),
        ("Register for the class by Friday.", True),
        ("He has prepared over 800 lessons for online instruction.", False),
        ("Albright began piano lessons at the age of 3.", False),
        ("Over the course of three boisterously received concerts...", False),
    ],
)
def test_class_in_description_needs_signup_wording(description, is_class):
    from local_events.normalizer import _infer_categories

    assert ("classes-&-lessons" in _infer_categories("Evening with the band", description, [])) is is_class


def test_deyra_parses_shadow_dom_template_markup():
    """The schedule now arrives as declarative shadow DOM; BeautifulSoup keeps
    <template> text as TemplateString, which get_text() skips."""
    from datetime import date

    from local_events.sources.deyra_schedule import DeyraScheduleSource

    html = (
        '<html><body><deyra-finder><template shadowrootmode="open"><div data-test="success"><article>'
        '<div class="o:grid"><div class="o:font-sunflower o:font-medium"><span>7:15 AM</span> - <span>8:00 AM</span></div>'
        '<div class="o:h6"><div class="">Lap Swimming</div></div>'
        '<div class="o:typography/regular"><div class="o:mb-1">Lap Pool (6 Lanes)</div></div><div></div></div>'
        '</article></div></template></deyra-finder></body></html>'
    )
    events = DeyraScheduleSource(name="y", url="https://example.test")._parse_day(html, date(2031, 6, 7), "https://example.test")
    assert [(e.title, e.start_time.strftime("%H:%M")) for e in events] == [("Lap Swimming", "07:15")]


@pytest.mark.anyio
async def test_deyra_no_longer_hides_failures(monkeypatch):
    from local_events.sources import deyra_schedule
    from local_events.sources.deyra_schedule import DeyraScheduleSource

    async def boom(*_a, **_k):
        raise RuntimeError("all scraper services failed")

    monkeypatch.setattr(deyra_schedule, "fetch_rendered_html", boom)
    with pytest.raises(RuntimeError):
        await DeyraScheduleSource(name="y", url="https://example.test", days_ahead=2).fetch()

    async def empty_shell(*_a, **_k):
        return "<html><body><deyra-finder></deyra-finder></body></html>", "https://example.test"

    monkeypatch.setattr(deyra_schedule, "fetch_rendered_html", empty_shell)
    src = DeyraScheduleSource(name="y", url="https://example.test", days_ahead=2)
    assert await src.fetch() == []
    assert src.partial_failures == ["2 day(s) rendered but no classes were found in them"]
