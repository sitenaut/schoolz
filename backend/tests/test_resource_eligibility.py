import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

import uuid
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from httpx import ASGITransport, AsyncClient
from sqlalchemy import delete, select, update

import database
from main import app
from models import ResourceEligibility, ResourceService
from resources import eligibility
from resources.eligibility import clean_criteria, extract_pending, quick_criteria, text_key


def test_stock_phrases_need_no_model_call():
    for text in ("Open to the public", "Open to the public.", "  open to ANYONE in the service area. ", "Open to all."):
        assert quick_criteria(text)["open_to_all"] is True, text
    for text in ("Call for eligibility information.", "Call for information", "Eligibility varies by program"):
        assert quick_criteria(text)["vague"] is True, text
    assert quick_criteria("Open to seniors aged 60 and over") is None


def test_one_key_for_the_same_sentence_however_it_is_spaced_or_punctuated():
    assert text_key("Open to the public") == text_key("open to the  public.")
    assert text_key("Open to the public") != text_key("Open to seniors")
    assert text_key(None) is None and text_key("  ") is None


def test_model_answers_are_held_to_the_vocabulary():
    raw = {
        "open_to_all": True,
        "age_min": 65,
        "age_max": "18",  # backwards, and a string
        "requires": ["veteran_military", "astronaut", "veteran_military"],
        "focus": ["women", "everyone"],
        "other": "  court referral  ",
        "surprise": "dropped",
    }
    out = clean_criteria(raw)
    assert (out["age_min"], out["age_max"]) == (18, 65)
    assert out["requires"] == ["veteran_military"] and out["focus"] == ["women"]
    assert out["other"] == "court referral"
    assert out["open_to_all"] is False  # a restriction wins over "open"
    assert "surprise" not in out
    assert clean_criteria({"age_min": 400, "requires": "veteran_military"})["age_min"] is None
    assert clean_criteria({"requires": "veteran_military"})["requires"] == []


class FakeClaude:
    """Answers each numbered sentence: "veteran" ones as veterans-only,
    anything else for 60 and over - except sentences containing "skip",
    which it leaves out, as a model sometimes does."""

    def __init__(self):
        self.calls: list[str] = []
        self.messages = self

    async def create(self, **kw):
        prompt = kw["messages"][0]["content"]
        self.calls.append(prompt)
        items = []
        for line in prompt.splitlines():
            n, _, text = line.partition(". ")
            if "skip" in text:
                continue
            items.append({"n": int(n), "requires": ["veteran_military"]} if "veteran" in text else {"n": int(n), "age_min": 60})
        usage = SimpleNamespace(input_tokens=10, output_tokens=10, cache_read_input_tokens=0, cache_creation_input_tokens=0)
        return SimpleNamespace(
            content=[SimpleNamespace(type="tool_use", input={"items": items})], stop_reason="tool_use", usage=usage, model="fake"
        )


async def _seed(eligibility_text, **overrides):
    fields = {
        "source": "test",
        "source_record_id": f"t-{uuid.uuid4()}",
        "name": "Test Service",
        "categories": ["food"],
        "taxonomy_codes": [],
        "taxonomy_names": [],
        "service_areas": [],
        "missing_core": [],
        "required_documents": [],
        "languages": [],
        "eligibility_text": eligibility_text,
        "last_seen_at": datetime.now(UTC),
        "first_seen_at": datetime.now(UTC) - timedelta(days=1),
    }
    fields.update(overrides)
    async with database.SessionLocal() as db:
        row = ResourceService(**fields)
        db.add(row)
        await db.commit()
        return row.id


@pytest.fixture
async def only_test_services():
    """Real crawled listings and their extracted criteria set aside for one
    test (rolled back after), so the extraction queue holds only this test's
    sentences."""
    async with database.SessionLocal() as db:
        await db.execute(update(ResourceService).where(ResourceService.source != "test").values(status="set-aside"))
        await db.execute(delete(ResourceEligibility))
        await db.commit()


@pytest.mark.anyio
async def test_each_distinct_sentence_is_read_once_and_kept(only_test_services):
    marker = uuid.uuid4().hex[:8]
    await _seed("Open to the public.")
    await _seed(f"Open to veterans and their families {marker}")
    await _seed(f"Open to veterans and their families {marker}.")  # same sentence
    await _seed(f"Seniors 60 and over {marker}")
    await _seed(f"Something odd, skip {marker}")
    await _seed(f"Inactive veterans {marker}", status="inactive")
    fake = FakeClaude()
    async with database.SessionLocal() as db:
        summary = await extract_pending(db, client=fake, model="fake")
    assert summary["eligibility_quick"] >= 1
    assert summary["eligibility_extracted"] == 2  # the skipped one stays pending
    assert len(fake.calls) == 1 and fake.calls[0].count(f"veterans and their families {marker}") == 1
    assert "Inactive" not in fake.calls[0]
    async with database.SessionLocal() as db:
        rows = {
            r.text: r
            for r in (await db.execute(select(ResourceEligibility).where(ResourceEligibility.text.contains(marker)))).scalars()
        }
    veterans = next(r for t, r in rows.items() if "veterans" in t)
    assert veterans.criteria["requires"] == ["veteran_military"] and veterans.version == eligibility.VERSION
    assert next(r for t, r in rows.items() if "Seniors" in t).criteria["age_min"] == 60

    # The next run asks only about what's still missing.
    fake = FakeClaude()
    async with database.SessionLocal() as db:
        summary = await extract_pending(db, client=fake, model="fake")
    assert summary["eligibility_pending"] == 1 and len(fake.calls) == 1 and "skip" in fake.calls[0]


@pytest.mark.anyio
async def test_a_failed_call_keeps_earlier_batches_and_reports_it(only_test_services, monkeypatch):
    monkeypatch.setattr(eligibility, "BATCH_SIZE", 1)
    marker = uuid.uuid4().hex[:8]
    await _seed(f"Seniors A {marker}")
    await _seed(f"Seniors B {marker}")

    class Flaky(FakeClaude):
        async def create(self, **kw):
            if self.calls:
                raise RuntimeError("overloaded")
            return await super().create(**kw)

    async with database.SessionLocal() as db:
        summary = await extract_pending(db, client=Flaky(), model="fake")
    assert summary["eligibility_extracted"] == 1
    assert summary["eligibility_errors"] and "overloaded" in summary["eligibility_errors"][0]


@pytest.mark.anyio
async def test_search_and_detail_carry_the_criteria(only_test_services):
    marker = uuid.uuid4().hex[:8]
    known = await _seed(f"Open to veterans {marker}", name=f"Vets {marker}")
    unread = await _seed(f"Not read yet {marker}", name=f"Unread {marker}")
    async with database.SessionLocal() as db:
        await db.merge(
            ResourceEligibility(
                text_key=text_key(f"Open to veterans {marker}"),
                text=f"Open to veterans {marker}",
                criteria=clean_criteria({"requires": ["veteran_military"]}),
                version=eligibility.VERSION,
                extracted_at=datetime.now(UTC),
            )
        )
        await db.commit()
    async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
        items = {i["id"]: i for i in (await client.post("/resources/search", json={"query": marker})).json()["items"]}
        assert items[known]["eligibility"]["requires"] == ["veteran_military"]
        assert items[unread]["eligibility"] is None
        assert (await client.get(f"/resources/{known}")).json()["eligibility"]["requires"] == ["veteran_military"]
