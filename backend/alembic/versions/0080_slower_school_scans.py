"""documents and staff rosters every two weeks, school info monthly, Smore spread

0075 made these three per-school scans weekly, which was still ~375
job-minutes a week through one 1GB Chromium. Handbooks and rosters change a
few times a year, so documents and staff_roster.scan move to two fixed days
of the month 14 apart, and school_info.scan (an address and a phone number)
to one. Smore scans stay weekly but each gets its own minute instead of all
24 firing at exactly Monday 8:00.

Only rows still on the cadence 0075 / the app gave them are touched (the
cron is recomputed and compared), so a cron set by hand survives. The hour
is unchanged. As in 0075 the hash and kind lists are copied here so this
migration keeps meaning the same thing if scheduler/cron.py changes later.

Revision ID: 0080
Revises: 0079
Create Date: 2026-10-07 22:00:00

"""
import hashlib
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0080"
down_revision: Union[str, None] = "0079"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_BIWEEKLY_KINDS = ("documents.scan", "staff_roster.scan")
_MONTHLY_KINDS = ("school_info.scan",)
_WEEKLY_HOURS = (0, 3, 4, 5, 22, 23)


def _hash(key: str) -> int:
    return int(hashlib.sha256(key.encode()).hexdigest(), 16)


def _old_cron(kind: str, target_id: str) -> str:
    h = _hash(f"{kind}:{target_id}")
    return f"{h % 60} {_WEEKLY_HOURS[(h // 60) % len(_WEEKLY_HOURS)]} * * {(h // 3600) % 7}"


def _new_cron(kind: str, target_id: str) -> str:
    h = _hash(f"{kind}:{target_id}")
    minute, hour = h % 60, _WEEKLY_HOURS[(h // 60) % len(_WEEKLY_HOURS)]
    if kind in _BIWEEKLY_KINDS:
        day = 1 + (h // 3600) % 14
        return f"{minute} {hour} {day},{day + 14} * *"
    return f"{minute} {hour} {1 + (h // 3600) % 28} * *"


def _smore_cron(newsletter_id: str) -> str:
    return f"{_hash(f'smore.scan:{newsletter_id}') % 60} 8 * * 1"


def _params(raw) -> dict:
    return json.loads(raw) if isinstance(raw, str) else (raw or {})


def _retime(rewrite) -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, kind, params, cron_expr FROM scheduled_jobs WHERE kind = ANY(:kinds)"),
        {"kinds": list(_BIWEEKLY_KINDS + _MONTHLY_KINDS + ("smore.scan",))},
    ).all()
    for job_id, kind, params, cron_expr in rows:
        params = _params(params)
        new = rewrite(kind, params, cron_expr)
        if new and new != cron_expr:
            conn.execute(sa.text("UPDATE scheduled_jobs SET cron_expr = :cron WHERE id = :id"), {"cron": new, "id": job_id})


def upgrade() -> None:
    def rewrite(kind, params, cron_expr):
        if kind == "smore.scan":
            nid = params.get("newsletter_id")
            return _smore_cron(nid) if nid and cron_expr == "0 8 * * 1" else None
        target = params.get("school_id")
        return _new_cron(kind, target) if target and cron_expr == _old_cron(kind, target) else None

    _retime(rewrite)


def downgrade() -> None:
    def rewrite(kind, params, cron_expr):
        if kind == "smore.scan":
            nid = params.get("newsletter_id")
            return "0 8 * * 1" if nid and cron_expr == _smore_cron(nid) else None
        target = params.get("school_id")
        return _old_cron(kind, target) if target and cron_expr == _new_cron(kind, target) else None

    _retime(rewrite)
