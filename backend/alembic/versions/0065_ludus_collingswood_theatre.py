"""Local events: Collingswood's school theatre program on Ludus.

Revision ID: 0065
Revises: 0064
Create Date: 2026-09-28 23:30:00

Adds a `ludus_sources` entry to the existing "Local events refresh: community
theatre" job (0063) rather than creating a new job - same cadence is plenty
for a ticketing page that changes rarely, and it keeps every theatre/show
source in one place. collstheater.ludus.com lists both Collingswood High
School and Collingswood Middle School's shows on one shared page, tagged
"CHS"/"CMS" - `school_labels` ties each to its real School.slug (from
backend/seed/collingswood_oaklyn_woodlynne.json) so a show is also published
on that school's own public page (local_events/school_sync.py), not just the
signed-in-only local events feed.
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0065"
down_revision: Union[str, None] = "0064"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_NAME = "Local events refresh: community theatre"

NEW_SOURCE = {
    "name": "collingswood_theater_ludus",
    "url": "https://collstheater.ludus.com/index.php?sections=events",
    "venue_name": "Collingswood Theater",
    "venue_address": "Collingswood, NJ",
    "default_categories": ["theatre", "arts", "school"],
    "school_labels": {
        "CHS": "collingswood-high",
        "CMS": "collingswood-middle",
    },
}


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id, params FROM scheduled_jobs WHERE name = :n"), {"n": JOB_NAME}
    ).first()
    if row is None:
        return  # 0063 hasn't run in this environment somehow - nothing to attach to
    params = row.params if isinstance(row.params, dict) else json.loads(row.params)
    ludus_sources = params.setdefault("ludus_sources", [])
    if any(s.get("name") == NEW_SOURCE["name"] for s in ludus_sources):
        return  # idempotent re-run
    ludus_sources.append(NEW_SOURCE)
    conn.execute(
        sa.text("UPDATE scheduled_jobs SET params = :p, updated_at = now() WHERE id = :id"),
        {"p": json.dumps(params), "id": row.id},
    )


def downgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id, params FROM scheduled_jobs WHERE name = :n"), {"n": JOB_NAME}
    ).first()
    if row is None:
        return
    params = row.params if isinstance(row.params, dict) else json.loads(row.params)
    params["ludus_sources"] = [s for s in params.get("ludus_sources", []) if s.get("name") != NEW_SOURCE["name"]]
    conn.execute(
        sa.text("UPDATE scheduled_jobs SET params = :p, updated_at = now() WHERE id = :id"),
        {"p": json.dumps(params), "id": row.id},
    )
