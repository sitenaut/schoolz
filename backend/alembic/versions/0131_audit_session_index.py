"""audit_events: index the Supabase session id

The first request of every session asks whether `auth.sign_in` was already
recorded for it (services/audit.py `_session_recorded`). With only
`ix_audit_events_action_ts`, that walked every sign-in row ever written, and
the table is append-only. Partial, so the rows that carry no session id (most
of them) stay out of it; the lookup's `=` implies the predicate. Built
concurrently: every audited request inserts into this table.

Revision ID: 0131
Revises: 0130
Create Date: 2026-10-24 00:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0131"
down_revision: str | None = "0130"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute(
            "CREATE INDEX CONCURRENTLY IF NOT EXISTS ix_audit_events_session_id ON audit_events "
            "((target ->> 'session_id')) WHERE (target ->> 'session_id') IS NOT NULL"
        )


def downgrade() -> None:
    with op.get_context().autocommit_block():
        op.execute("DROP INDEX CONCURRENTLY IF EXISTS ix_audit_events_session_id")
