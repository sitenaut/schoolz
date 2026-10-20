"""llm_usage: one row per model call's token counts, for the daily cost report

Written by services/llm_ledger.py whenever observability.record_llm_call runs;
read by the llm_cost.report job. Additive: a new table, nothing reads it until
the code that writes it is deployed.

Revision ID: 0120
Revises: 0119
Create Date: 2026-10-20 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0120"
down_revision: str | None = "0119"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("purpose", sa.String(64), nullable=False),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("service", sa.String(40), nullable=True),
        sa.Column("stop_reason", sa.String(40), nullable=True),
        sa.Column("input_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("output_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_read_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("cache_write_tokens", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index("ix_llm_usage_created_at", "llm_usage", ["created_at"])
    op.execute("ALTER TABLE llm_usage ENABLE ROW LEVEL SECURITY")
    op.execute(
        """
        DO $$ BEGIN
          IF EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'grafana_ro') THEN
            GRANT SELECT ON llm_usage TO grafana_ro;
            CREATE POLICY grafana_ro_read ON llm_usage FOR SELECT TO grafana_ro USING (true);
          END IF;
        END $$
        """
    )


def downgrade() -> None:
    op.drop_table("llm_usage")
