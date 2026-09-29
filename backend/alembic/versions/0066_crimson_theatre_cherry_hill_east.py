"""Local events: Cherry Hill East's Crimson Theatre program.

Revision ID: 0066
Revises: 0065
Create Date: 2026-09-29 00:40:00

Crimson Theatre is Cherry Hill High School East's own theatre program, but
its real public calendar lives on the CHE Theatre Boosters site
(chetb.weebly.com), not on any resale marketplace that happens to list the
venue (boxofficeticketsales.com/venues/cherry-hill-high-school-east is a
resale aggregator, not East's own listing - confirmed by its "as a resale
marketplace, prices may be above face value" banner). Performances are
staged at Cherry Hill West's Old Auditorium, but the program and its
Theatre Boosters belong to East, hence `school_slug` = East, not West.

Routed through the existing Haiku-based `theatre_sources` (prose, not a
structured platform like Ludus) - confirmed against the real page that the
model still needs the deterministic backstage-jargon filter added to
theatre.py (it kept "Crimson Theatre Tech" as a production even when told to
skip tech days, since the word "Theatre" already in the title reads as a
real show name).
"""
import json
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0066"
down_revision: Union[str, None] = "0065"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

JOB_NAME = "Local events refresh: community theatre"

NEW_SOURCE = {
    "name": "cherry_hill_east_crimson_theatre",
    "urls": ["http://chetb.weebly.com/events.html"],
    "venue_name": "Cherry Hill High School West - Old Auditorium",
    "default_categories": ["theatre", "arts", "school"],
    "school_slug": "cherry-hill-high-school-east",
}


def upgrade() -> None:
    conn = op.get_bind()
    row = conn.execute(
        sa.text("SELECT id, params FROM scheduled_jobs WHERE name = :n"), {"n": JOB_NAME}
    ).first()
    if row is None:
        return
    params = row.params if isinstance(row.params, dict) else json.loads(row.params)
    theatre_sources = params.setdefault("theatre_sources", [])
    if any(s.get("name") == NEW_SOURCE["name"] for s in theatre_sources):
        return  # idempotent re-run
    theatre_sources.append(NEW_SOURCE)
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
    params["theatre_sources"] = [s for s in params.get("theatre_sources", []) if s.get("name") != NEW_SOURCE["name"]]
    conn.execute(
        sa.text("UPDATE scheduled_jobs SET params = :p, updated_at = now() WHERE id = :id"),
        {"p": json.dumps(params), "id": row.id},
    )
