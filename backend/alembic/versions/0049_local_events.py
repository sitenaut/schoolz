"""local_events: community events feed (port of billz's events table) + its refresh job

Revision ID: 0049
Revises: 0048
Create Date: 2026-09-22 12:00:00

"""
import copy
import json
import uuid
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0049"
down_revision: Union[str, None] = "0048"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "local_events",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("source", sa.Text(), nullable=False),
        sa.Column("source_event_id", sa.Text(), nullable=False),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("start_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("end_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("all_day", sa.Boolean(), nullable=False, server_default="false"),
        sa.Column("venue_name", sa.Text(), nullable=True),
        sa.Column("venue_address", sa.Text(), nullable=True),
        sa.Column("latitude", sa.Float(), nullable=True),
        sa.Column("longitude", sa.Float(), nullable=True),
        sa.Column("url", sa.Text(), nullable=True),
        sa.Column("image_url", sa.Text(), nullable=True),
        sa.Column("price_min", sa.Numeric(10, 2), nullable=True),
        sa.Column("price_max", sa.Numeric(10, 2), nullable=True),
        sa.Column("is_free", sa.Boolean(), nullable=True),
        sa.Column("categories", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
        sa.Column("raw", postgresql.JSONB(), nullable=True),
        sa.Column("fetched_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False),
        sa.UniqueConstraint("source", "source_event_id", name="uq_local_events_source_event"),
    )
    op.create_index("ix_local_events_start_time", "local_events", ["start_time"])
    op.create_index("ix_local_events_categories", "local_events", ["categories"], postgresql_using="gin")
    op.execute("ALTER TABLE local_events ENABLE ROW LEVEL SECURITY")

    # Seed the refresh job with billz's own defaults, so /local has data
    # without an admin first hand-entering sources. phila.gov's Google
    # Calendar list is left out: it's ~30 city-government calendars
    # (Wedding Schedule, Tax Review Board, ...) - noise for Cherry Hill
    # families. It stays in the job kind's "Insert defaults" for anyone who
    # wants it. Imported rather than copied so the two can't drift.
    from scheduler.jobs.local_events_refresh import DEFAULT_PARAMS

    params = copy.deepcopy(DEFAULT_PARAMS)
    params["gcal_sources"] = []
    job = sa.table(
        "scheduled_jobs",
        sa.column("id", sa.String),
        sa.column("kind", sa.String),
        sa.column("name", sa.String),
        sa.column("description", sa.String),
        sa.column("cron_expr", sa.String),
        sa.column("timezone", sa.String),
        sa.column("params", sa.JSON),
        sa.column("enabled", sa.Boolean),
        sa.column("run_once", sa.Boolean),
        sa.column("created_at", sa.DateTime(timezone=True)),
        sa.column("updated_at", sa.DateTime(timezone=True)),
    )
    op.execute(
        job.insert().values(
            id=str(uuid.uuid4()),
            kind="local_events.refresh",
            name="Local events refresh",
            description="Community events for /local - sources are edited as JSON params (Test fetch before saving).",
            cron_expr="0 */6 * * *",
            timezone="America/New_York",
            params=json.loads(json.dumps(params)),
            enabled=True,
            run_once=False,
            created_at=sa.func.now(),
            updated_at=sa.func.now(),
        )
    )


def downgrade() -> None:
    op.execute("DELETE FROM scheduled_jobs WHERE kind = 'local_events.refresh'")
    op.drop_index("ix_local_events_categories", table_name="local_events")
    op.drop_index("ix_local_events_start_time", table_name="local_events")
    op.drop_table("local_events")
