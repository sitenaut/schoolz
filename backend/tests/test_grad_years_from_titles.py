"""Which high-school class an item is for, read from its title (any source,
at save: models._grad_years_from_title) or from the newsletter model's stated
audience (services/content_extractor.py), so the calendar and the family feed
stop showing every class's trips and meetings to every family."""
import os
import uuid
from datetime import date, datetime, time, timedelta
from types import SimpleNamespace
from zoneinfo import ZoneInfo

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import select, update

import database
from main import app
from models import District, School, SchoolContentItem, SmoreBlock, SmoreNewsletter, User
from services.class_years import current_grad_years, grad_years_in_title, grades_to_grad_years

ET = ZoneInfo("America/New_York")
NOV = date(2026, 11, 12)  # enrolled: 2027 (seniors) through 2030 (freshmen)


@pytest.mark.parametrize(
    "title, years",
    [
        ("College Night for Juniors (Class of 2028)", [2028]),
        ("College Night for Juniors (Class of '28)", [2028]),
        ("College Night for Juniors (Class of ’28)", [2028]),
        ("Class of 2028 & 2029 Movie Night", [2028, 2029]),
        ("CLASSES OF 2027, 2028, and 2029 Car Wash", [2027, 2028, 2029]),
        ("FIELD TRIP: Class of 2028/Key Club to Philly Navy Yard 5K", [2028]),
        ("2027 Senior Trip Final Deposit Due / Pajamology", [2027]),
        ("Optional Deposit #2 - Class of 2029 Senior Trip 2029", [2029]),
        ("WHS: Class of 2027 | Paint the Lot", [2027]),
        # Not one of the four enrolled classes: whole school.
        ("HSS High School Program of Studies - Class of 2031", None),
        ("Class of 2026 Graduation Rehearsal", None),
        ("Willingboro High School Alumni Brunch - Class of 1976", None),
        # Names no class.
        ("Senior Portraits", None),
        ("Senior Citizen Matinee", None),
        ("Yoga, a class of 30", None),
        ("", None),
        (None, None),
    ],
)
def test_a_title_names_its_class(title, years):
    assert grad_years_in_title(title, NOV) == years


def test_the_classes_are_the_ones_enrolled_on_the_items_date():
    # The seniors of a June 2027 graduation are 2027; by September they're gone.
    assert grad_years_in_title("Class of 2027 Graduation", date(2027, 6, 17)) == [2027]
    assert grad_years_in_title("Class of 2027 Graduation", date(2027, 9, 10)) is None
    # 10pm on June 30 is stored as 02:00 UTC on July 1; at school it's still
    # June 30, the old school year.
    late = datetime(2027, 7, 1, 2, 0, tzinfo=ZoneInfo("UTC"))
    assert grad_years_in_title("Class of 2027 Picnic", late) == [2027]


def test_a_stated_audience_names_its_classes():
    assert grades_to_grad_years(["seniors"], NOV) == [2027]
    assert grades_to_grad_years(["Juniors", " seniors "], NOV) == [2027, 2028]
    assert grades_to_grad_years(["10th graders", "11th graders", "12th graders"], NOV) == [2027, 2028, 2029]
    assert grades_to_grad_years(["5th graders"], NOV) is None
    assert grades_to_grad_years([], NOV) is None
    assert grades_to_grad_years("seniors", NOV) is None  # not a list: the schema isn't enforced
    assert grades_to_grad_years(None, NOV) is None


async def _schools(db, *types: str) -> tuple[District, list[School]]:
    tag = uuid.uuid4().hex[:8]
    district = District(name=f"Class Years {tag}")
    db.add(district)
    await db.flush()
    schools = [School(name=f"{t.title()} {tag}", slug=f"cy-{t}-{tag}", school_type=t, district_id=district.id) for t in types]
    db.add_all(schools)
    await db.flush()
    return district, schools


@pytest.mark.anyio
async def test_any_source_saving_a_high_schools_class_item_tags_it():
    seniors, juniors, sophomores = current_grad_years()[:3]
    async with database.SessionLocal() as db:
        district, (high, elementary) = await _schools(db, "high", "elementary")
        on_district = {"scope": "district", "district_id": district.id}
        rows = {
            "feed": SchoolContentItem(school_id=high.id, category="event", title=f"WHS Class of {juniors} Meeting", source="ics_feed"),
            "whole school": SchoolContentItem(school_id=high.id, category="event", title="Senior Portraits", source="ics_feed"),
            "set by its source": SchoolContentItem(
                school_id=high.id, category="event", title=f"Class of {juniors} Car Wash", source="hs_activities_site", applies_to_grad_years=[sophomores]
            ),
            "elementary": SchoolContentItem(school_id=elementary.id, category="event", title=f"PTA Pretzel Pre-Sale (Class of {seniors})", source="newsletter"),
            "district": SchoolContentItem(**on_district, category="event", title=f"Class of {seniors} Graduation", source="ics_feed"),
            "district, high only": SchoolContentItem(
                **on_district, category="event", title=f"Class of {seniors} Senior Sunrise", source="ics_feed", applies_to_school_types=["high"]
            ),
            "district, elementary only": SchoolContentItem(
                **on_district, category="event", title=f"Class of {seniors} Clap-Out", source="ics_feed", applies_to_school_types=["elementary"]
            ),
        }
        db.add_all(rows.values())
        await db.flush()
        tagged = {name: row.applies_to_grad_years for name, row in rows.items()}
        assert tagged == {
            "feed": [juniors],
            "whole school": None,
            "set by its source": [sophomores],
            "elementary": None,
            "district": [seniors],
            "district, high only": [seniors],
            "district, elementary only": None,
        }

        # A feed that renames its event in place is read again.
        renamed = rows["whole school"]
        renamed.title = f"Senior Portraits (Class of {seniors})"
        await db.flush()
        assert renamed.applies_to_grad_years == [seniors]


@pytest.mark.anyio
async def test_a_high_school_newsletter_reads_who_an_item_is_for(monkeypatch):
    from services import content_extractor

    seniors, juniors = current_grad_years()[:2]
    items = [
        {"category": "event", "title": "Senior Portraits", "audience_grades": ["seniors"]},
        {"category": "event", "title": f"Junior Prom (Class of {juniors})", "audience_grades": ["seniors"]},
        {"category": "event", "title": "Back to School Night"},
        {"category": "event", "title": "Powder Puff Football", "audience_grades": ["juniors", "seniors"]},
    ]

    class _Messages:
        async def create(self, **kwargs):
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"items": [dict(i) for i in items]})], stop_reason="tool_use", usage=None)

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(content_extractor, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(content_extractor, "AsyncAnthropic", _Client)
    async with database.SessionLocal() as db:
        _district, (high, elementary) = await _schools(db, "high", "elementary")
        found = {}
        for school in (high, elementary):
            newsletter = SmoreNewsletter(url=f"https://example.org/{uuid.uuid4().hex}", school_id=school.id)
            db.add(newsletter)
            await db.flush()
            await content_extractor.extract_from_newsletter(db, newsletter, [SmoreBlock(position=0, block_type="text", text_content="x")])
            rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()
            found[school.school_type] = {r.title: r.applies_to_grad_years for r in rows}

    assert found["high"] == {
        "Senior Portraits": [seniors],
        # The title says which class; the model's reading doesn't override it.
        f"Junior Prom (Class of {juniors})": [juniors],
        "Back to School Night": None,
        "Powder Puff Football": [seniors, juniors],
    }
    # A lower school's "seniors" are no high-school class.
    assert set(found["elementary"].values()) == {None}


def _auth(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


@pytest.mark.anyio
async def test_the_family_feed_leaves_out_other_classes_items():
    seniors, juniors, sophomores = current_grad_years()[:3]
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        email = f"cy_{uuid.uuid4().hex[:10]}@example.com"
        res = await client.post("/auth/register", json={"email": email, "username": f"u_{uuid.uuid4().hex[:10]}", "password": "password123"})
        admin = res.json()["access_token"]
        async with database.SessionLocal() as db:
            await db.execute(update(User).where(User.email == email).values(is_admin=True))
            _district, (high,) = await _schools(db, "high")
            high_id = high.id
            await db.commit()
        child = await client.post(
            "/students",
            json={"first_name": "Sky", "last_name": "Classtest", "student_id": uuid.uuid4().hex[:8], "school_id": high_id},
            headers=_auth(admin),
        )
        assert child.status_code == 201, child.text
        res = await client.patch(f"/students/{child.json()['id']}", json={"grad_year": sophomores}, headers=_auth(admin))
        assert res.status_code == 200, res.text

        on = datetime.combine(datetime.now(ET).date() + timedelta(days=2), time(19), ET)
        titles = [f"Class of {seniors} Senior Trip Deposit Due", f"College Night for Juniors (Class of '{juniors % 100})", f"Class of {sophomores} Movie Night", "Winter Concert"]
        async with database.SessionLocal() as db:
            db.add_all(SchoolContentItem(school_id=high_id, category="event", title=t, source="newsletter", start_date=on) for t in titles)
            await db.commit()

        res = await client.get("/family/feed", headers=_auth(admin))
        assert res.status_code == 200, res.text
        shown = {i["title"] for i in res.json()["items"] if i["kind"] == "event"}
        assert shown == {f"Class of {sophomores} Movie Night", "Winter Concert"}
