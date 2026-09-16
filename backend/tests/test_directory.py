import os
import uuid

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import pytest
from httpx import ASGITransport, AsyncClient

import database
from main import app
from models import School, StaffMember
from services.staff_roles import classify_directory_category


async def _seed() -> tuple[str, str]:
    """Two schools with a handful of staff each. Every test here scopes its
    assertions to these slugs - the local dev database this suite runs
    against already holds ~1900 real staff rows, so a bare total would be
    whatever the last roster scan left behind."""
    tag = uuid.uuid4().hex[:8]
    elem_slug, middle_slug = f"dirtest-elem-{tag}", f"dirtest-mid-{tag}"
    async with database.SessionLocal() as db:
        elem = School(name=f"Dirtest Elementary {tag}", slug=elem_slug, short_name="Dirtest Elem", school_type="elementary")
        middle = School(name=f"Dirtest Middle {tag}", slug=middle_slug, short_name="Dirtest Mid", school_type="middle")
        db.add_all([elem, middle])
        await db.flush()
        db.add_all(
            [
                StaffMember(school_id=elem.id, source_constituent_id="1", full_name="Ada Quibble", title="Math Teacher", email="ada@example.com"),
                StaffMember(school_id=elem.id, source_constituent_id="2", full_name="Ben Quibble", title="Principal", email="ben@example.com"),
                StaffMember(school_id=elem.id, source_constituent_id="3", full_name="Cara Quibble", title="Nurse", phone="(856) 555-0100"),
                # No title at all - a real and common shape (596 such rows in
                # prod). Has to stay findable by name.
                StaffMember(school_id=elem.id, source_constituent_id="4", full_name="Dana Quibble"),
                StaffMember(school_id=middle.id, source_constituent_id="5", full_name="Evan Quibble", title="Math Teacher"),
            ]
        )
        await db.commit()
    return elem_slug, middle_slug


def _names(body: dict) -> list[str]:
    return [i["full_name"] for i in body["items"]]


@pytest.mark.anyio
async def test_directory_is_public_and_spans_schools():
    elem_slug, _ = await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # No Authorization header anywhere in this file - the directory is
        # public by the same rule as every other read in this app.
        res = await client.get("/directory/staff", params={"q": "quibble", "limit": 200})
        assert res.status_code == 200, res.text
        body = res.json()
        assert body["total"] == 5
        assert set(_names(body)) == {"Ada Quibble", "Ben Quibble", "Cara Quibble", "Dana Quibble", "Evan Quibble"}
        # Each row carries its own school, which is the whole point of the
        # aggregate view over 27 per-school pages.
        assert {i["school_short_name"] for i in body["items"]} == {"Dirtest Elem", "Dirtest Mid"}
        ada = next(i for i in body["items"] if i["full_name"] == "Ada Quibble")
        assert ada["school_slug"] == elem_slug and ada["category"] == "teacher"


@pytest.mark.anyio
async def test_search_tokens_are_anded_across_fields():
    await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        # "quibble math" has to mean "named Quibble AND teaches math", not
        # "matches either word" - an OR would return all five.
        res = await client.get("/directory/staff", params={"q": "quibble math", "limit": 200})
        assert sorted(_names(res.json())) == ["Ada Quibble", "Evan Quibble"]

        # A token can match the school as well as the person.
        res = await client.get("/directory/staff", params={"q": "quibble dirtest middle", "limit": 200})
        assert _names(res.json()) == ["Evan Quibble"]

        # An untitled person is still findable by name.
        res = await client.get("/directory/staff", params={"q": "dana quibble"})
        assert _names(res.json()) == ["Dana Quibble"]


@pytest.mark.anyio
async def test_school_filter_accepts_slug_and_school_type():
    elem_slug, _ = await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/directory/staff", params={"school_id": elem_slug, "limit": 200})
        assert sorted(_names(res.json())) == ["Ada Quibble", "Ben Quibble", "Cara Quibble", "Dana Quibble"]

        res = await client.get("/directory/staff", params={"q": "quibble", "school_type": "middle", "limit": 200})
        assert _names(res.json()) == ["Evan Quibble"]


@pytest.mark.anyio
async def test_category_filter_and_facet_counts():
    elem_slug, _ = await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        res = await client.get("/directory/staff", params={"school_id": elem_slug, "limit": 200})
        body = res.json()
        counts = {c["key"]: c["count"] for c in body["categories"]}
        assert counts == {"teacher": 1, "office": 1, "health": 1, "other": 1}
        # Chips only list categories that would actually return something.
        assert all(c["count"] > 0 for c in body["categories"])

        res = await client.get("/directory/staff", params={"school_id": elem_slug, "category": "health"})
        assert _names(res.json()) == ["Cara Quibble"]

        # Facets describe the search result set, not the category-filtered
        # one - otherwise picking a chip would collapse every other chip to
        # zero and there'd be no way back.
        filtered = res.json()
        assert {c["key"] for c in filtered["categories"]} == {"teacher", "office", "health", "other"}


@pytest.mark.anyio
async def test_pagination_is_stable_and_reports_total():
    elem_slug, _ = await _seed()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        first = await client.get("/directory/staff", params={"school_id": elem_slug, "limit": 2, "offset": 0})
        second = await client.get("/directory/staff", params={"school_id": elem_slug, "limit": 2, "offset": 2})
        assert first.json()["total"] == second.json()["total"] == 4
        # Ordered by name, so the pages partition the list rather than
        # repeating rows.
        assert _names(first.json()) == ["Ada Quibble", "Ben Quibble"]
        assert _names(second.json()) == ["Cara Quibble", "Dana Quibble"]

        too_big = await client.get("/directory/staff", params={"limit": 500})
        assert too_big.status_code == 422


def test_category_classification_of_real_title_shapes():
    # Shapes taken from the live Cherry Hill rosters - the ordering traps
    # the pattern list exists to handle.
    assert classify_directory_category("Athletic Director") == "athletics"
    assert classify_directory_category("Assistant Principal Class of 2027") == "office"
    assert classify_directory_category("Administrative Assistant") == "office"
    assert classify_directory_category("Guidance Counselor") == "support"
    assert classify_directory_category("Preschool Instructional Coach") == "support"
    assert classify_directory_category("Educational Assistant") == "aide"
    assert classify_directory_category("Special Education Teacher") == "teacher"
    assert classify_directory_category("Night Lead Custodian") == "facilities"
    assert classify_directory_category("Nurse") == "health"
    # No title: falls back to the department, then to the catch-all.
    assert classify_directory_category(None, "Preschool Administration") == "office"
    assert classify_directory_category(None, "Guidance") == "support"
    assert classify_directory_category(None, None) == "other"
