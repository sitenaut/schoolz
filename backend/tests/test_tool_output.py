import json
import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from types import SimpleNamespace

import pytest
from bs4 import BeautifulSoup
from sqlalchemy import select

import database
from models import School, SchoolContentItem
from services import hs_activities_site
from services.tool_output import object_list, object_value, recover_spilled_input

ITEM = {"title": "Fall Play", "category": "event", "start_date": "2026-10-02"}


def test_a_real_list_passes_through():
    assert object_list([ITEM]) == ([ITEM], [])


def test_a_list_sent_as_a_json_string_is_decoded():
    # The confirmed real failure on Cherry Hill West's activities site.
    assert object_list(json.dumps([ITEM])) == ([ITEM], [])


def test_entries_that_are_json_strings_are_decoded_and_junk_is_reported():
    kept, dropped = object_list([json.dumps(ITEM), "not an item", 7, ITEM])
    assert kept == [ITEM, ITEM] and dropped == ["not an item", 7]


def test_a_whole_array_nested_as_one_string_entry_is_flattened():
    # Also confirmed real on West's yearbook page.
    assert object_list([json.dumps([ITEM, ITEM])]) == ([ITEM, ITEM], [])


@pytest.mark.parametrize("value, expected", [(None, ([], [])), ("garbage", ([], ["garbage"])), (ITEM, ([ITEM], []))])
def test_odd_shapes(value, expected):
    assert object_list(value) == expected


def test_the_rest_of_the_call_spilled_into_items_is_recovered():
    # The real West class-of-2027 shape: the array, then the next argument,
    # all inside the `items` string.
    spilled = json.dumps([ITEM], indent=2) + ',\n"class_year_facts": {\n  "advisor_names": ["A. Advisor"],\n  "instagram_url": "@chw2027"\n}\n'
    data = recover_spilled_input({"items": spilled})
    assert data["items"] == [ITEM]
    assert data["class_year_facts"] == {"advisor_names": ["A. Advisor"], "instagram_url": "@chw2027"}
    # A key the call did carry properly is never overwritten.
    assert recover_spilled_input({"items": spilled, "class_year_facts": {"instagram_url": "@real"}})["class_year_facts"] == {"instagram_url": "@real"}


def test_recovery_leaves_everything_else_alone():
    assert recover_spilled_input({"items": [ITEM]}) == {"items": [ITEM]}
    assert recover_spilled_input({"items": json.dumps([ITEM])}) == {"items": json.dumps([ITEM])}
    assert recover_spilled_input({"items": "not json"}) == {"items": "not json"}
    assert recover_spilled_input(None) == {}


def test_object_value():
    assert object_value(json.dumps({"a": 1})) == {"a": 1}
    assert object_value("nope") == {} and object_value(None) == {}


def _patch_scan(monkeypatch, items_value):
    class _Messages:
        async def create(self, **_):
            block = SimpleNamespace(type="tool_use", input={"items": items_value})
            return SimpleNamespace(content=[block], stop_reason="tool_use",
                                   usage=SimpleNamespace(input_tokens=1, output_tokens=1,
                                                         cache_read_input_tokens=0, cache_creation_input_tokens=0))

    async def one_page(base_url, client):
        return [base_url]

    async def fetch(url, client):
        return BeautifulSoup("<main><p>Fall Play - October 2</p></main>", "lxml")

    monkeypatch.setattr(hs_activities_site, "ANTHROPIC_API_KEY", "test")
    monkeypatch.setattr(hs_activities_site, "AsyncAnthropic", lambda api_key: SimpleNamespace(messages=_Messages()))
    monkeypatch.setattr(hs_activities_site, "discover_pages", one_page)
    monkeypatch.setattr(hs_activities_site, "_fetch", fetch)
    monkeypatch.setattr(hs_activities_site.observability, "record_llm_call", lambda *a, **k: None)


async def _school(db, slug):
    school = School(name=slug, slug=slug, school_type="high", activities_site_url="https://sites.google.com/example/home")
    db.add(school)
    await db.flush()
    return school


@pytest.mark.anyio
async def test_activities_scan_survives_items_returned_as_a_string(monkeypatch):
    _patch_scan(monkeypatch, json.dumps([ITEM, "junk"]))
    async with database.SessionLocal() as db:
        school = await _school(db, "tool-output-test-high")
        summary = await hs_activities_site.scan_activities_site(db, school)
        await db.commit()
        rows = (await db.execute(select(SchoolContentItem).where(SchoolContentItem.school_id == school.id))).scalars().all()

    assert "1 item(s) created" in summary
    assert [r.title for r in rows] == ["Fall Play"]


@pytest.mark.anyio
async def test_a_page_with_unreadable_output_keeps_its_existing_items(monkeypatch):
    _patch_scan(monkeypatch, "not json at all")
    async with database.SessionLocal() as db:
        school = await _school(db, "tool-output-retire-test")
        kept = SchoolContentItem(scope="school", school_id=school.id, source="hs_activities_site", category="event",
                                 title="Yearbook Ordering", is_current=True, external_uid="site:/example/home:abc")
        db.add(kept)
        await db.flush()
        summary = await hs_activities_site.scan_activities_site(db, school)
        await db.refresh(kept)

    assert "retired" not in summary
    assert kept.is_current
