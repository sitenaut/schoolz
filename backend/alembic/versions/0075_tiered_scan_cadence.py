"""move heavy static scans to weekly and menus to daily

0057 gave every 12h public scan its own minute, but the per-school
documents/school-info/staff-roster scans still added up to ~6.6h of job
time per cycle through a 3-slot scraper client, so each cycle queued for
~2h and roster scans failed in the tail. Rewrites those kinds to the
cadence scheduler/cron.py:public_scan_cron now gives a new job: weekly on
a hashed night+hour, daily for menus. Calendar-feed kinds keep 12h.

Only rows still on the automatic "M */12 * * *" pattern are touched, so a
cron set by hand survives. The minute is unchanged, which is what lets
the downgrade restore the old value exactly.

The hash and kind lists are copied here rather than imported so this
migration keeps meaning the same thing if scheduler/cron.py changes later.

Revision ID: 0075
Revises: 0074
Create Date: 2026-10-04 12:00:00

"""
import hashlib
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0075"
down_revision: Union[str, None] = "0074"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_WEEKLY_KINDS = (
    "documents.scan",
    "school_info.scan",
    "staff_roster.scan",
    "marking_period.scan",
    "preschool_locations.scan",
    "preschool_team.scan",
    "transportation.scan",
    "hs_rotation.scan",
)
_DAILY_KINDS = (
    "lunch_menu.scan",
    "schoolcafe_menu.scan",
    "fdmealplanner_menu.scan",
    "healthepro_menu.scan",
    "presence_menu.scan",
    "givebacks.scan",
    "hs_activities_site.scan",
)
_WEEKLY_HOURS = (0, 3, 4, 5, 22, 23)
_DAILY_HOURS = (3, 4, 5)


def _cron(kind: str, target_id: str) -> str:
    h = int(hashlib.sha256(f"{kind}:{target_id}".encode()).hexdigest(), 16)
    minute = h % 60
    if kind in _WEEKLY_KINDS:
        return f"{minute} {_WEEKLY_HOURS[(h // 60) % len(_WEEKLY_HOURS)]} * * {(h // 3600) % 7}"
    return f"{minute} {_DAILY_HOURS[(h // 60) % len(_DAILY_HOURS)]} * * *"


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text(
            r"SELECT id, kind, params FROM scheduled_jobs "
            r"WHERE kind = ANY(:kinds) AND cron_expr ~ '^[0-9]+ \*/12 \* \* \*$'"
        ),
        {"kinds": list(_WEEKLY_KINDS + _DAILY_KINDS)},
    ).all()
    for job_id, kind, params in rows:
        params = json.loads(params) if isinstance(params, str) else (params or {})
        target = params.get("school_id") or params.get("district_id") or job_id
        conn.execute(
            sa.text("UPDATE scheduled_jobs SET cron_expr = :cron WHERE id = :id"),
            {"cron": _cron(kind, target), "id": job_id},
        )


def downgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, kind, params, cron_expr FROM scheduled_jobs WHERE kind = ANY(:kinds)"),
        {"kinds": list(_WEEKLY_KINDS + _DAILY_KINDS)},
    ).all()
    for job_id, kind, params, cron_expr in rows:
        params = json.loads(params) if isinstance(params, str) else (params or {})
        target = params.get("school_id") or params.get("district_id") or job_id
        if cron_expr == _cron(kind, target):
            conn.execute(
                sa.text("UPDATE scheduled_jobs SET cron_expr = :cron WHERE id = :id"),
                {"cron": f"{cron_expr.split()[0]} */12 * * *", "id": job_id},
            )
