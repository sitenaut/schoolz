"""scheduler_heartbeats: the scheduler's proof of life, one row per tick

The scheduler-down alert used to be a metric (schoolz_scheduler_reconciles_total),
which goes silent the same way whether the scheduler died or telemetry export
broke. This row is read by Grafana's Postgres datasource instead. Additive: a
new table, nothing reads it until the code that writes it is deployed.

grafana_ro exists only in prod (created by hand, see docs/OBSERVABILITY_PLAN.md),
so its grant is applied only where the role exists.

Revision ID: 0119
Revises: 0118
Create Date: 2026-10-19 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0119"
down_revision: str | None = "0118"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "scheduler_heartbeats",
        sa.Column("id", sa.String(20), primary_key=True),
        sa.Column("machine_id", sa.String(64), nullable=True),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("ALTER TABLE scheduler_heartbeats ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
            GRANT SELECT ON scheduler_heartbeats TO grafana_ro;
            CREATE POLICY grafana_ro_read ON scheduler_heartbeats FOR SELECT TO grafana_ro USING (true);
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.drop_table("scheduler_heartbeats")
