"""audit_events: who did what to whom, append-only (services/audit.py)

A trigger refuses UPDATE and DELETE on the table, so a bug or a compromised
process can't rewrite history. No foreign keys, so removing a user never
removes their events. Additive: one table, its indexes, a trigger function
and the trigger; safe before the code that writes to it is deployed.

Revision ID: 0116
Revises: 0115
Create Date: 2026-10-18 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0116"
down_revision: str | None = "0115"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("ts", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("action", sa.String(64), nullable=False),
        sa.Column("outcome", sa.String(16), nullable=False),
        sa.Column("status", sa.Integer(), nullable=True),
        sa.Column("actor_user_id", sa.String(36), nullable=True),
        sa.Column("credential", sa.String(16), nullable=True),
        sa.Column("api_key_id", sa.String(36), nullable=True),
        sa.Column("method", sa.String(8), nullable=True),
        sa.Column("route", sa.String(200), nullable=True),
        sa.Column("target", postgresql.JSONB(), nullable=True),
        sa.Column("ip_hash", sa.String(64), nullable=True),
        sa.Column("request_id", sa.String(64), nullable=True),
    )
    op.create_index("ix_audit_events_ts", "audit_events", ["ts"])
    op.create_index("ix_audit_events_actor_ts", "audit_events", ["actor_user_id", "ts"])
    op.create_index("ix_audit_events_action_ts", "audit_events", ["action", "ts"])
    op.execute(
        """
        CREATE FUNCTION audit_events_append_only() RETURNS trigger
        LANGUAGE plpgsql AS $$
        BEGIN
            RAISE EXCEPTION 'audit_events is append-only';
        END;
        $$
        """
    )
    op.execute(
        """
        CREATE TRIGGER audit_events_append_only
        BEFORE UPDATE OR DELETE ON audit_events
        FOR EACH ROW EXECUTE FUNCTION audit_events_append_only()
        """
    )


def downgrade() -> None:
    # Deliberately empty: an append-only history is never dropped by a downgrade.
    pass
