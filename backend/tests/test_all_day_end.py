import uuid
from datetime import date, datetime
from types import SimpleNamespace

import pytest

import database
from models import District, School, SmoreBlock, SmoreNewsletter
from services import content_extractor
from services.content_extractor import _DEFAULT_TZ, all_day_end
from services.school_today import build_today


def test_all_day_end_is_the_day_after_the_printed_last_day():
    nov5, nov6 = datetime(2026, 11, 5, tzinfo=_DEFAULT_TZ), datetime(2026, 11, 6, tzinfo=_DEFAULT_TZ)
    assert all_day_end(nov5, nov6, True) == datetime(2026, 11, 7, tzinfo=_DEFAULT_TZ)
    assert all_day_end(nov5, nov5, True) is None  # one day is no range
    assert all_day_end(nov5, None, True) is None
    timed_end = datetime(2026, 11, 6, 21, 0, tzinfo=_DEFAULT_TZ)
    assert all_day_end(nov5, timed_end, False) == timed_end


@pytest.mark.anyio
async def test_a_two_day_closure_from_a_newsletter_closes_both_days(monkeypatch):
    class _Messages:
        async def create(self, **kwargs):
            item = {"category": "event", "title": "No School - NJEA Convention", "scope": "district",
                    "start_date": "2026-11-05", "end_date": "2026-11-06"}
            return SimpleNamespace(content=[SimpleNamespace(type="tool_use", input={"items": [item]})], stop_reason="tool_use", usage=None)

    class _Client:
        def __init__(self, **kwargs):
            self.messages = _Messages()

    monkeypatch.setattr(content_extractor, "ANTHROPIC_API_KEY", "test-key")
    monkeypatch.setattr(content_extractor, "AsyncAnthropic", _Client)
    async with database.SessionLocal() as db:
        tag = uuid.uuid4().hex[:8]
        district = District(name=f"NJEA District {tag}")
        db.add(district)
        await db.flush()
        school = School(name=f"NJEA School {tag}", slug=f"njea-{tag}", district_id=district.id, school_type="elementary")
        db.add(school)
        newsletter = SmoreNewsletter(url=f"https://example.org/{uuid.uuid4().hex}", district_id=district.id)
        db.add(newsletter)
        await db.flush()
        await content_extractor.extract_from_newsletter(db, newsletter, [SmoreBlock(position=0, block_type="text", text_content="x")])
        await db.flush()
        assert (await build_today(db, school, date(2026, 11, 5))).status == "closed"
        assert (await build_today(db, school, date(2026, 11, 6))).status == "closed"
        assert (await build_today(db, school, date(2026, 11, 9))).status == "open"
