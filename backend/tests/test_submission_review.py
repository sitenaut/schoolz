import os
import uuid
from datetime import date, datetime, timedelta
from types import SimpleNamespace

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import School, SchoolContentItem, User
from services import submission_review
from services.content_extractor import _DEFAULT_TZ
from services.submission_review import item_flags, note_flags, similar_titles


def _draft(**kw):
    base = dict(
        title="Fall cleaning", start_local="2026-11-01T13:00:00", stated_weekday=None, tentative=False,
        reader_note=None, content_item_id=None, replaces_item_id=None,
    )
    return SimpleNamespace(**{**base, **kw})


TODAY = date(2026, 10, 5)


def _codes(flags):
    return [f["code"] for f in flags]


def test_printed_weekday_that_disagrees_with_the_date_holds_the_item():
    # The real flyer: "Wednesday, November 17th" - Nov 17, 2026 is a Tuesday.
    flags = item_flags(_draft(title="Next PTA meeting", start_local="2026-11-17T18:00:00", stated_weekday="Wednesday"), [], TODAY)
    assert _codes(flags) == ["weekday_mismatch"]
    assert flags[0]["hold"] is True
    assert "Tuesday" in flags[0]["text"]


def test_matching_weekday_raises_nothing():
    assert item_flags(_draft(stated_weekday="Sunday"), [], TODAY) == []


def test_undated_item_is_held_and_nothing_else_is_reported():
    flags = item_flags(_draft(start_local=None, tentative=True, reader_note="x"), [], TODAY)
    assert _codes(flags) == ["no_date"]


def test_handwritten_correction_and_tentative_inform_without_holding():
    flags = item_flags(_draft(reader_note="Printed 'November 11', handwritten '1st' over it.", tentative=True), [], TODAY)
    assert _codes(flags) == ["reader_note", "tentative"]
    assert not any(f["hold"] for f in flags)


def test_past_date_holds():
    assert _codes(item_flags(_draft(start_local="2026-10-01"), [], TODAY)) == ["past"]


def test_similar_item_already_on_the_calendar_holds_until_marked_as_replacing():
    existing = [("abc", "Tatem Fall Festival at Knight Park", date(2026, 10, 24))]
    draft = _draft(title="PTA Fall Festival", start_local="2026-10-24T12:00:00")
    flags = item_flags(draft, existing, TODAY)
    assert _codes(flags) == ["already_listed"] and flags[0]["hold"] and flags[0]["item_id"] == "abc"

    draft.replaces_item_id = "abc"
    assert item_flags(draft, existing, TODAY)[0]["hold"] is False

    # Same title on a different day is a different event.
    assert item_flags(_draft(title="PTA Fall Festival", start_local="2026-10-25"), existing, TODAY) == []


def test_unrelated_same_day_item_is_not_a_duplicate():
    assert not similar_titles("Movie on the Blacktop", "Picture Day")
    assert similar_titles("First Day of Autumn", "1st Day of Autumn")


def test_note_naming_a_date_no_item_has_is_reported():
    # The real case: the page says Nov 1, the parent's note said the 10th.
    drafts = [_draft(), _draft(title="Tap Takeover", start_local="2026-10-14T17:00:00")]
    flags = note_flags("Notice the fall cleaning is November 10th", drafts)
    assert len(flags) == 1 and "Nov 10" in flags[0]
    assert note_flags("Fall cleaning is Nov 1st and the takeover is 10/14", drafts) == []
    assert note_flags(None, drafts) == []


# --- API flow ---------------------------------------------------------------

FLYER = [
    {"title": "PTA Tatem Tap Takeover", "category": "pta", "start": "2026-10-14T17:00:00", "end": "2026-10-14T22:00:00",
     "stated_weekday": None, "tentative": False, "description": "Raccoon Taproom", "reader_note": None,
     "source_excerpt": "PTA Tatem Tap Takeover - October 14, 5-10 pm - Raccoon Taproom"},
    {"title": "Movie on the Blacktop", "category": "event", "start": "2026-10-23T18:30:00", "end": None,
     "stated_weekday": None, "tentative": True, "description": None, "reader_note": None,
     "source_excerpt": "Movie on the Blacktop - October 23rd (tentative), 6:30 pm"},
    {"title": "Next PTA meeting", "category": "pta", "start": "2026-11-17T18:00:00", "end": None,
     "stated_weekday": "Wednesday", "tentative": False, "description": "In the APR", "reader_note": None,
     "source_excerpt": "NEXT PTA MEETING - Wednesday, November 17th, 6 pm in the APR"},
    {"title": "Read-a-Thon", "category": "funding", "start": None, "end": None, "stated_weekday": None,
     "tentative": False, "description": None, "reader_note": None, "source_excerpt": "Coming up: ... Read-a-Thon"},
    {"title": "", "category": "event", "start": "2026-10-01"},  # junk row: skipped, not fatal
    {"title": "Odd date", "category": "nonsense", "start": "next Tuesday", "end": None, "stated_weekday": "Someday",
     "tentative": False, "description": None, "reader_note": None, "source_excerpt": "x"},
]


async def _admin_headers(client: AsyncClient) -> dict[str, str]:
    tag = uuid.uuid4().hex[:8]
    email = f"rev_admin_{tag}@example.com"
    res = await client.post("/auth/register", json={"email": email, "username": f"rev_admin_{tag}", "password": "password123"})
    assert res.status_code == 201, res.text
    async with database.SessionLocal() as db:
        await db.execute(update(User).where(User.email == email).values(is_admin=True))
        await db.commit()
    return {"Authorization": f"Bearer {res.json()['access_token']}"}


async def _school() -> str:
    tag = uuid.uuid4().hex[:8]
    async with database.SessionLocal() as db:
        school = School(name=f"Review Test School {tag}", slug=f"review-test-{tag}")
        db.add(school)
        await db.commit()
        return school.id


@pytest.fixture
def fake_reader(monkeypatch):
    # Fixed "today" so the flyer's October dates stay in the future.
    monkeypatch.setattr(submission_review, "today_local", lambda: TODAY)

    async def _read(data, **kwargs):
        return [c for c in (submission_review._clean_item(i) for i in FLYER) if c]

    monkeypatch.setattr(submission_review, "read_upload", _read)


async def _uploaded(client, **data) -> str:
    res = await client.post("/submissions", files={"file": ("agenda.jpg", b"\xff\xd8\xff fake", "image/jpeg")}, data=data)
    assert res.status_code == 201, res.text
    return res.json()["id"]


@pytest.mark.anyio
async def test_read_then_publish_puts_only_the_chosen_items_on_the_calendar(fake_reader):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        school_id = await _school()
        sid = await _uploaded(client, description="the takeover is Oct 14, meeting is November 18")

        assert (await client.post(f"/submissions/{sid}/extract")).status_code == 401

        review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        by_title = {i["title"]: i for i in review["items"]}
        assert set(by_title) == {"PTA Tatem Tap Takeover", "Movie on the Blacktop", "Next PTA meeting", "Read-a-Thon", "Odd date"}
        assert [f["code"] for f in by_title["Next PTA meeting"]["flags"]] == ["weekday_mismatch"]
        assert [f["code"] for f in by_title["Read-a-Thon"]["flags"]] == ["no_date"]
        assert by_title["Odd date"]["start_local"] is None and by_title["Odd date"]["category"] == "event"
        assert len(review["note_flags"]) == 1 and "Nov 18" in review["note_flags"][0]
        assert review["submission"]["status"] == "pending"

        ids = [by_title["PTA Tatem Tap Takeover"]["id"], by_title["Movie on the Blacktop"]["id"]]
        no_school = await client.post(f"/submissions/{sid}/publish", json={"item_ids": ids}, headers=admin)
        assert no_school.status_code == 400

        assert (await client.patch(f"/submissions/{sid}", json={"school_id": school_id}, headers=admin)).status_code == 200
        undated = await client.post(f"/submissions/{sid}/publish", json={"item_ids": [by_title["Read-a-Thon"]["id"]]}, headers=admin)
        assert undated.status_code == 400

        published = await client.post(f"/submissions/{sid}/publish", json={"item_ids": ids}, headers=admin)
        assert published.status_code == 200, published.text
        assert published.json()["submission"]["status"] == "approved"

        async with database.SessionLocal() as db:
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school_id))).scalars().all()
        assert {r.title for r in rows} == {"PTA Tatem Tap Takeover", "Movie on the Blacktop (tentative)"}
        takeover = next(r for r in rows if r.title.startswith("PTA"))
        assert takeover.source == "community" and takeover.is_all_day is False
        # 5 pm Eastern, not 5 pm UTC.
        assert takeover.start_date.astimezone(_DEFAULT_TZ).hour == 17
        assert takeover.end_date.astimezone(_DEFAULT_TZ).hour == 22

        # The public school feed now carries them, with no login.
        content = await client.get(f"/schools/{school_id}/content")
        assert content.status_code == 200 and "PTA Tatem Tap Takeover" in content.text

        # Publishing the same ids again adds nothing.
        again = await client.post(f"/submissions/{sid}/publish", json={"item_ids": ids}, headers=admin)
        assert again.status_code == 400


@pytest.mark.anyio
async def test_reading_again_keeps_typed_and_published_items(fake_reader):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        school_id = await _school()
        sid = await _uploaded(client)
        await client.patch(f"/submissions/{sid}", json={"school_id": school_id}, headers=admin)
        review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        takeover = next(i for i in review["items"] if i["title"] == "PTA Tatem Tap Takeover")
        await client.post(f"/submissions/{sid}/publish", json={"item_ids": [takeover["id"]]}, headers=admin)
        added = await client.post(
            f"/submissions/{sid}/items", json={"title": "Fall cleaning", "start_local": "2026-11-01T13:00:00"}, headers=admin
        )
        assert added.status_code == 201, added.text

        review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        titles = [i["title"] for i in review["items"]]
        assert titles.count("Fall cleaning") == 1
        assert titles.count("Movie on the Blacktop") == 1  # replaced, not doubled
        published = [i for i in review["items"] if i["content_item_id"]]
        assert [i["id"] for i in published] == [takeover["id"]]


@pytest.mark.anyio
async def test_editing_a_published_item_changes_the_calendar_and_unpublish_removes_it(fake_reader):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        school_id = await _school()
        sid = await _uploaded(client)
        await client.patch(f"/submissions/{sid}", json={"school_id": school_id}, headers=admin)
        review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        meeting = next(i for i in review["items"] if i["title"] == "Next PTA meeting")

        # Moving the date to the real Wednesday clears the mismatch.
        fixed = await client.patch(
            f"/submissions/{sid}/items/{meeting['id']}", json={"start_local": "2026-11-18T18:00:00"}, headers=admin
        )
        assert next(i for i in fixed.json()["items"] if i["id"] == meeting["id"])["flags"] == []

        await client.post(f"/submissions/{sid}/publish", json={"item_ids": [meeting["id"]]}, headers=admin)
        await client.patch(f"/submissions/{sid}/items/{meeting['id']}", json={"title": "PTA meeting"}, headers=admin)
        async with database.SessionLocal() as db:
            row = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school_id))).scalar_one()
        assert row.title == "PTA meeting" and row.start_date.astimezone(_DEFAULT_TZ).day == 18

        blocked = await client.delete(f"/submissions/{sid}/items/{meeting['id']}", headers=admin)
        assert blocked.status_code == 400

        off = await client.post(f"/submissions/{sid}/items/{meeting['id']}/unpublish", headers=admin)
        assert off.status_code == 200 and off.json()["submission"]["status"] == "pending"
        async with database.SessionLocal() as db:
            assert (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school_id))).first() is None


@pytest.mark.anyio
async def test_replacing_an_existing_item_retires_it_and_unpublish_restores_it(fake_reader):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        school_id = await _school()
        async with database.SessionLocal() as db:
            old = SchoolContentItem(
                scope="school", school_id=school_id, category="event", title="Tatem Tap Takeover",
                start_date=datetime(2026, 10, 14, 18, 0, tzinfo=_DEFAULT_TZ),
            )
            db.add(old)
            await db.commit()
            old_id = old.id

        sid = await _uploaded(client)
        await client.patch(f"/submissions/{sid}", json={"school_id": school_id}, headers=admin)
        review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        takeover = next(i for i in review["items"] if i["title"] == "PTA Tatem Tap Takeover")
        assert takeover["flags"][0]["code"] == "already_listed" and takeover["flags"][0]["item_id"] == old_id

        await client.patch(f"/submissions/{sid}/items/{takeover['id']}", json={"replaces_item_id": old_id}, headers=admin)
        await client.post(f"/submissions/{sid}/publish", json={"item_ids": [takeover["id"]]}, headers=admin)
        async with database.SessionLocal() as db:
            assert (await db.execute(select(SchoolContentItem.is_current).where(SchoolContentItem.id == old_id))).scalar_one() is False

        await client.post(f"/submissions/{sid}/items/{takeover['id']}/unpublish", headers=admin)
        async with database.SessionLocal() as db:
            assert (await db.execute(select(SchoolContentItem.is_current).where(SchoolContentItem.id == old_id))).scalar_one() is True


@pytest.mark.anyio
async def test_a_link_submission_has_nothing_to_read():
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        sid = (await client.post("/submissions", data={"url": "https://example.com/n"})).json()["id"]
        assert (await client.post(f"/submissions/{sid}/extract", headers=admin)).status_code == 400
        review = await client.get(f"/submissions/{sid}", headers=admin)
        assert review.status_code == 200 and review.json()["items"] == []


LOCAL_FLYER = [
    {"title": "Harvest Fest", "category": "event", "start": "2026-10-17T11:00:00", "end": "2026-10-17T15:00:00",
     "stated_weekday": "Saturday", "tentative": False, "description": "Hayrides, kids' crafts, <b>free</b> cider",
     "reader_note": None, "venue_name": "Barclay Farmstead", "venue_address": "209 Greentree Rd, Cherry Hill, NJ",
     "source_excerpt": "HARVEST FEST Sat Oct 17, 11-3 at Barclay Farmstead"},
]


@pytest.mark.anyio
async def test_a_local_item_publishes_to_local_events_without_a_school_and_comes_back_off(monkeypatch):
    from local_events.prune import prune_orphaned_events
    from models import LocalEvent

    monkeypatch.setattr(submission_review, "today_local", lambda: TODAY)

    async def _read(data, **kwargs):
        return [c for c in (submission_review._clean_item(i) for i in LOCAL_FLYER) if c]

    monkeypatch.setattr(submission_review, "read_upload", _read)

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        sid = await _uploaded(client)  # no school on the submission
        review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        draft = review["items"][0]
        assert draft["venue_name"] == "Barclay Farmstead" and draft["scope"] == "school"

        # As a school item it still needs a school...
        assert (await client.post(f"/submissions/{sid}/publish", json={"item_ids": [draft["id"]]}, headers=admin)).status_code == 400
        # ...but the reviewer can send it to /local instead.
        bad = await client.patch(f"/submissions/{sid}/items/{draft['id']}", json={"local_categories": ["nonsense"]}, headers=admin)
        assert bad.status_code == 400
        assert "music" in review["local_categories"]
        moved = await client.patch(
            f"/submissions/{sid}/items/{draft['id']}",
            json={"scope": "local", "local_categories": ["music", "classes-&-lessons"]},
            headers=admin,
        )
        assert moved.status_code == 200, moved.text
        published = await client.post(f"/submissions/{sid}/publish", json={"item_ids": [draft["id"]]}, headers=admin)
        assert published.status_code == 200, published.text
        item = published.json()["items"][0]
        assert item["local_event_id"] and item["content_item_id"] is None
        assert published.json()["submission"]["status"] == "approved"

        async with database.SessionLocal() as db:
            event = (await db.execute(select(LocalEvent).where(LocalEvent.id == item["local_event_id"]))).scalar_one()
            assert event.source == "community" and event.venue_name == "Barclay Farmstead"
            assert event.description == "Hayrides, kids' crafts, free cider"  # markup stripped like any feed
            assert "free" in event.categories and "family" in event.categories  # inferred from the text
            assert {"music", "classes-&-lessons"} <= set(event.categories)  # picked by the reviewer
            # 11 am Eastern, not UTC.
            assert event.start_time.astimezone(_DEFAULT_TZ).hour == 11 and event.all_day is False
            # A job edit/delete prunes orphaned sources; this one has no job.
            await prune_orphaned_events(db)
            assert (await db.execute(select(LocalEvent).where(LocalEvent.id == event.id))).scalar_one_or_none() is not None

        # Moving a published item between destinations needs an unpublish first.
        blocked = await client.patch(f"/submissions/{sid}/items/{draft['id']}", json={"scope": "school"}, headers=admin)
        assert blocked.status_code == 400
        assert (await client.delete(f"/submissions/{sid}/items/{draft['id']}", headers=admin)).status_code == 400

        # Editing it edits the live event.
        await client.patch(f"/submissions/{sid}/items/{draft['id']}", json={"venue_name": "Barclay Farm"}, headers=admin)
        async with database.SessionLocal() as db:
            assert (await db.execute(select(LocalEvent.venue_name).where(LocalEvent.id == event.id))).scalar_one() == "Barclay Farm"

        # Reading again leaves the published draft alone.
        again = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
        assert [i["local_event_id"] for i in again["items"] if i["local_event_id"]] == [event.id]

        off = await client.post(f"/submissions/{sid}/items/{draft['id']}/unpublish", headers=admin)
        assert off.status_code == 200 and off.json()["submission"]["status"] == "pending"
        assert off.json()["items"][0]["local_event_id"] is None
        async with database.SessionLocal() as db:
            assert (await db.execute(select(LocalEvent).where(LocalEvent.id == event.id))).scalar_one_or_none() is None


@pytest.mark.anyio
async def test_a_local_draft_is_flagged_when_a_feed_already_has_the_event(monkeypatch):
    from models import LocalEvent

    monkeypatch.setattr(submission_review, "today_local", lambda: TODAY)
    async with database.SessionLocal() as db:
        db.add(
            LocalEvent(
                source="some-feed", source_event_id=uuid.uuid4().hex, title="Harvest Fest at Barclay Farmstead",
                start_time=datetime(2026, 10, 17, 15, 0, tzinfo=_DEFAULT_TZ), categories=[],
            )
        )
        await db.commit()

    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        sid = await _uploaded(client)
        added = await client.post(
            f"/submissions/{sid}/items",
            json={"title": "Harvest Fest", "scope": "local", "start_local": "2026-10-17T11:00:00"},
            headers=admin,
        )
        flags = added.json()["items"][0]["flags"]
        assert [f["code"] for f in flags] == ["already_listed"] and flags[0]["hold"] is True


@pytest.mark.anyio
async def test_items_start_on_local_when_the_sender_flagged_a_local_event_and_named_no_school(fake_reader):
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        admin = await _admin_headers(client)
        flagged = await _uploaded(client, description="[Local event] harvest fest")
        plain = await _uploaded(client, description="PTA stuff")
        for sid, expected in ((flagged, "local"), (plain, "school")):
            review = (await client.post(f"/submissions/{sid}/extract", headers=admin)).json()
            assert {i["scope"] for i in review["items"]} == {expected}

        # A named school wins: the sender's hint only fills in when nothing else says where.
        school_id = await _school()
        both = await _uploaded(client, description="[Local event] x")
        await client.patch(f"/submissions/{both}", json={"school_id": school_id}, headers=admin)
        review = (await client.post(f"/submissions/{both}/extract", headers=admin)).json()
        assert {i["scope"] for i in review["items"]} == {"school"}
