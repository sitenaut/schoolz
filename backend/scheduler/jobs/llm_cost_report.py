"""Scheduled job: email the owner what model calls cost in the last 24 hours,
by purpose and model, against the day before and the 7-day average, with a
14-day trend.

Priced from `llm_usage` (services/llm_ledger.py) at services/llm_prices.py's
list prices - an estimate, not the invoice. It is the per-purpose breakdown
the invoice can't give, and it needs no Anthropic Admin key on an app machine
(that key stays in Grafana). A call that timed out is billed but has no
usage, so it is missing here; the email says so.

Rows older than `days_kept` are deleted at the end of each run.
"""
from __future__ import annotations

from collections import defaultdict
from datetime import UTC, date, datetime, timedelta
from zoneinfo import ZoneInfo

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from models import LlmUsage
from scheduler.registry import register_job
from services import llm_prices, mailer

LOCAL_TZ = ZoneInfo("America/New_York")
TREND_DAYS = 14

PARAM_SCHEMA = {
    "type": "object",
    "properties": {
        "to": {"type": "string", "description": "Who gets the report (one address)."},
        "days_kept": {"type": "integer", "minimum": 15, "description": "Days of llm_usage rows to keep."},
    },
    "required": ["to"],
}

_SUMS = (
    func.count(LlmUsage.id),
    func.coalesce(func.sum(LlmUsage.input_tokens), 0),
    func.coalesce(func.sum(LlmUsage.output_tokens), 0),
    func.coalesce(func.sum(LlmUsage.cache_write_tokens), 0),
    func.coalesce(func.sum(LlmUsage.cache_read_tokens), 0),
)


def _cost(model: str, inp: int, out: int, cw: int, cr: int) -> float | None:
    return llm_prices.cost(model, inp, out, cw, cr)


def _usd(x: float) -> str:
    return f"${x:,.2f}" if x >= 0.995 or x == 0 else f"${x:.3f}"


def _calls(n: int) -> str:
    return f"{n:,} call" + ("" if n == 1 else "s")


def _change(now: float, before: float) -> str:
    if before <= 0:
        return "n/a"
    pct = (now - before) / before * 100
    return f"{pct:+.0f}%"


async def build_report(db: AsyncSession, now: datetime) -> tuple[str, str, dict]:
    """(subject, body, totals) for the 24 hours ending `now`."""
    day_ago, two_days_ago = now - timedelta(hours=24), now - timedelta(hours=48)

    rows = (await db.execute(
        select(LlmUsage.purpose, LlmUsage.model, *_SUMS).where(LlmUsage.created_at >= day_ago).group_by(LlmUsage.purpose, LlmUsage.model)
    )).all()
    by_purpose: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0.0])
    by_model: dict[str, list] = defaultdict(lambda: [0, 0, 0, 0.0])
    unpriced: set[str] = set()
    total = 0.0
    calls = 0
    for purpose, model, n, inp, out, cw, cr in rows:
        c = _cost(model, inp, out, cw, cr)
        if c is None:
            unpriced.add(model)
            c = 0.0
        for bucket in (by_purpose[purpose], by_model[model]):
            bucket[0] += n
            bucket[1] += inp + cw + cr
            bucket[2] += out
            bucket[3] += c
        total += c
        calls += n

    async def window_cost(start: datetime, end: datetime) -> float:
        got = (await db.execute(
            select(LlmUsage.model, *_SUMS[1:]).where(LlmUsage.created_at >= start, LlmUsage.created_at < end).group_by(LlmUsage.model)
        )).all()
        return sum(_cost(m, i, o, w, r) or 0.0 for m, i, o, w, r in got)

    previous = await window_cost(two_days_ago, day_ago)

    # Daily totals by local calendar day, the last TREND_DAYS days (today partial).
    today = now.astimezone(LOCAL_TZ).date()
    first = today - timedelta(days=TREND_DAYS - 1)
    local_day = func.date(func.timezone("America/New_York", LlmUsage.created_at))
    since = datetime.combine(first, datetime.min.time(), LOCAL_TZ)
    daily_rows = (await db.execute(
        select(local_day, LlmUsage.model, *_SUMS[1:]).where(LlmUsage.created_at >= since).group_by(local_day, LlmUsage.model)
    )).all()
    daily: dict[date, float] = defaultdict(float)
    for d, model, i, o, w, r in daily_rows:
        daily[d] += _cost(model, i, o, w, r) or 0.0
    full_days = [daily.get(today - timedelta(days=k), 0.0) for k in range(1, 8)]
    recorded_days = [v for k, v in zip(range(1, 8), full_days, strict=True) if (today - timedelta(days=k)) in daily]
    week_avg = sum(recorded_days) / len(recorded_days) if recorded_days else 0.0

    lines = [
        f"Model spend, 24 hours to {now.astimezone(LOCAL_TZ):%a %b %-d, %-I:%M %p} ET",
        "",
        f"  Total:            {_usd(total)}  ({_calls(calls)})",
        f"  Previous 24h:     {_usd(previous)}  ({_change(total, previous)})",
        f"  7-day daily avg:  {_usd(week_avg)}  ({_change(total, week_avg)})",
        f"  At this rate:     {_usd(total * 30)} / 30 days",
        "",
        "By purpose",
    ]
    for purpose, (n, inp, out, c) in sorted(by_purpose.items(), key=lambda kv: -kv[1][3]):
        lines.append(f"  {purpose:<28} {_usd(c):>8}  {_calls(n):>11}  {inp:>10,} in  {out:>9,} out")
    if not by_purpose:
        lines.append("  (no calls)")
    lines += ["", "By model"]
    for model, (n, _inp, _out, c) in sorted(by_model.items(), key=lambda kv: -kv[1][3]):
        lines.append(f"  {model:<28} {_usd(c):>8}  {_calls(n):>11}" + ("  (no price on file)" if model in unpriced else ""))
    if not by_model:
        lines.append("  (no calls)")

    lines += ["", f"Last {TREND_DAYS} days (ET, today so far)"]
    peak = max(daily.values(), default=0.0) or 1.0
    for k in range(TREND_DAYS - 1, -1, -1):
        d = today - timedelta(days=k)
        v = daily.get(d, 0.0)
        bar = "#" * max(1, round(v / peak * 30)) if v else ""
        lines.append(f"  {d:%a %b %d}  {_usd(v):>8}  {bar}")

    lines += [
        "",
        "Estimated from list prices and the token counts schoolz records for",
        "every call that returned a reply. A call that timed out is still billed",
        "but has nothing to record, so the invoice (the Cost page in Anthropic's",
        "Console) can run slightly higher.",
    ]
    subject = f"schoolz model spend: {_usd(total)} in 24h ({_change(total, week_avg)} vs 7-day avg)"
    return subject, "\n".join(lines), {"total": round(total, 4), "calls": calls, "previous": round(previous, 4), "week_avg": round(week_avg, 4)}


@register_job(
    kind="llm_cost.report",
    default_name="Daily model cost report",
    default_cron="0 7 * * *",
    default_params={"to": "", "days_kept": 90},
    description="Emails what model calls cost in the last 24h by purpose and model, with the 7-day average and a 14-day trend. Deletes llm_usage rows past days_kept.",
    param_schema=PARAM_SCHEMA,
)
async def run(db: AsyncSession, params: dict) -> str | None:
    to = (params.get("to") or "").strip()
    if not to:
        return "WARNING[cost_report_no_recipient]: set params.to to the address that gets the report"
    subject, body, totals = await build_report(db, datetime.now(UTC))
    mailer.queue(db, kind="llm_cost.report", to=to, subject=subject, body=body, expires_in=timedelta(days=2))
    days_kept = max(int(params.get("days_kept") or 90), 15)
    pruned = (await db.execute(delete(LlmUsage).where(LlmUsage.created_at < datetime.now(UTC) - timedelta(days=days_kept)))).rowcount
    await db.commit()
    sent = await mailer.send_pending(limit=20)
    summary = f"{subject} · pruned {pruned} rows · {totals}"
    if sent.get("waiting"):
        return f"WARNING[email_not_configured]: report queued but SMTP isn't set up · {summary}"
    if sent.get("failed"):
        return f"WARNING[email_failed]: report didn't send (email.outbox retries) · {summary}"
    return summary
