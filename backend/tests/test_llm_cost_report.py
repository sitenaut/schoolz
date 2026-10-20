import os

os.environ.setdefault("JWT_SECRET", "test-secret")
os.environ.setdefault("AUTH_MODE", "local")

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from sqlalchemy import select

import database
import observability
from models import LlmUsage, OutboundEmail
from scheduler.jobs import llm_cost_report
from services import llm_ledger, llm_prices, mailer


def test_prices_match_the_published_list_and_unknown_models_are_unpriced():
    # 1M in + 1M out on each model, at Anthropic's list prices.
    assert llm_prices.cost("claude-haiku-5-5", 1_000_000, 1_000_000, 0, 0) == pytest.approx(0.60)
    assert llm_prices.cost("claude-haiku-4-5-20251001", 1_000_000, 1_000_000, 0, 0) == pytest.approx(6.00)
    assert llm_prices.cost("claude-opus-5-5", 1_000_000, 0, 0, 0) == pytest.approx(4.00)
    assert llm_prices.cost("claude-opus-5", 1_000_000, 0, 0, 0) == pytest.approx(5.00)
    assert llm_prices.cost("gemini-2.5-flash", 1_000_000, 0, 0, 0) is None


def test_the_meter_skips_the_ledger_under_pytest_and_never_raises():
    # No running loop and PYTEST_CURRENT_TEST set: note() is a no-op, and
    # record_llm_call still records its metrics.
    response = SimpleNamespace(stop_reason="end_turn", usage=SimpleNamespace(input_tokens=5, output_tokens=7))
    observability.record_llm_call("content_translation", "claude-haiku-5-5", response, 0.1)
    assert not llm_ledger._PENDING


async def _row(purpose, model, when, inp, out):
    await llm_ledger.write({"purpose": purpose, "model": model, "service": "test", "stop_reason": "tool_use",
                            "input_tokens": inp, "output_tokens": out, "cache_read_tokens": 0, "cache_write_tokens": 0})
    async with database.SessionLocal() as db:
        row = (await db.execute(select(LlmUsage).order_by(LlmUsage.created_at.desc()).limit(1))).scalar_one()
        row.created_at = when
        await db.commit()


@pytest.mark.anyio
async def test_the_report_prices_the_last_24h_by_purpose_and_compares_it(monkeypatch):
    now = datetime.now(UTC)
    async with database.SessionLocal() as db:
        await db.execute(LlmUsage.__table__.delete())  # rolled back with the test
        await db.commit()
    await _row("content_translation", "claude-haiku-5-5", now - timedelta(hours=1), 1_000_000, 1_000_000)  # $0.60
    await _row("content_extract", "claude-haiku-4-5-20251001", now - timedelta(hours=2), 100_000, 0)  # $0.10
    await _row("chat", "gemini-2.5-flash", now - timedelta(hours=3), 500, 500)  # unpriced
    await _row("content_translation", "claude-haiku-4-5-20251001", now - timedelta(hours=30), 1_000_000, 1_000_000)  # $6.00 day before
    await _row("vision_extract", "claude-haiku-4-5-20251001", now - timedelta(days=200), 1_000_000, 0)  # pruned

    async with database.SessionLocal() as db:
        subject, body, totals = await llm_cost_report.build_report(db, now)
    assert totals["total"] == pytest.approx(0.70)
    assert totals["previous"] == pytest.approx(6.00)
    assert subject.startswith("schoolz model spend: $0.700 in 24h")
    assert "-88%" in body  # 0.70 against 6.00
    lines = body.splitlines()
    by_purpose = lines[lines.index("By purpose") + 1:lines.index("By model") - 1]
    assert by_purpose[0].split()[0] == "content_translation"  # costliest first
    assert any("gemini-2.5-flash" in ln and "no price on file" in ln for ln in lines)
    assert "Last 14 days" in body

    monkeypatch.setattr(mailer, "_send_sync", lambda messages, s: [None] * len(messages))
    monkeypatch.setattr(mailer, "configured", lambda: True)
    async with database.SessionLocal() as db:
        result = await llm_cost_report.run(db, {"to": "owner@example.org", "days_kept": 90})
    assert "pruned 1 rows" in result
    async with database.SessionLocal() as db:
        assert (await db.execute(select(OutboundEmail).where(OutboundEmail.kind == "llm_cost.report"))).scalars().first()
        left = (await db.execute(select(LlmUsage))).scalars().all()
    assert len(left) == 4


@pytest.mark.anyio
async def test_no_recipient_is_a_warning_not_a_silent_success():
    async with database.SessionLocal() as db:
        result = await llm_cost_report.run(db, {"to": ""})
    assert result.startswith("WARNING[cost_report_no_recipient]")
