"""spread the 12h public-source scans across the hour

Every "0 */12 * * *" job gets its own minute, the same one
scheduler/cron.py:public_scan_cron gives a new job for that kind and
target. All ~85 used to start in the same minute against one 1GB Chromium,
and the heaviest sites timed out mid-burst (up to 32 of 84 runs failed with
site_did_not_load; none failed on a manual run).

The hash is copied here rather than imported so this migration keeps
meaning the same thing if scheduler/cron.py changes later.

Revision ID: 0057
Revises: 0056
Create Date: 2026-09-26 15:30:00

"""
import hashlib
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0057"
down_revision: Union[str, None] = "0056"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

_OLD = "0 */12 * * *"


def _minute(kind: str, target_id: str) -> int:
    return int(hashlib.sha256(f"{kind}:{target_id}".encode()).hexdigest(), 16) % 60


def upgrade() -> None:
    conn = op.get_bind()
    rows = conn.execute(sa.text("SELECT id, kind, params FROM scheduled_jobs WHERE cron_expr = :old"), {"old": _OLD}).all()
    for job_id, kind, params in rows:
        params = json.loads(params) if isinstance(params, str) else (params or {})
        target = params.get("school_id") or params.get("district_id") or job_id
        conn.execute(
            sa.text("UPDATE scheduled_jobs SET cron_expr = :cron WHERE id = :id"),
            {"cron": f"{_minute(kind, target)} */12 * * *", "id": job_id},
        )


def downgrade() -> None:
    op.execute(r"UPDATE scheduled_jobs SET cron_expr = '0 */12 * * *' WHERE cron_expr ~ '^[0-9]+ \*/12 \* \* \*$'")
