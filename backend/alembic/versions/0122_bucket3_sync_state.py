"""bucket3_sync_state: when each Backpack Capture source was last read, per student

Written by the bucket3 import and capture-status routes, read by
GET /students/{id}/bucket3/status (Gradez's "Updated 2 h ago"). Additive: a
new table; until it has a row, the status route falls back to the newest
stored capture.

Revision ID: 0122
Revises: 0121
Create Date: 2026-10-21 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0122"
down_revision: str | None = "0121"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "bucket3_sync_state",
        sa.Column(
            "student_id",
            sa.String(36),
            sa.ForeignKey("students.id", ondelete="CASCADE"),
            primary_key=True,
        ),
        sa.Column("classroom_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("genesis_seen_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("walk_status", sa.String(40), nullable=True),
        sa.Column("walk_detail", sa.String(300), nullable=True),
        sa.Column("walk_finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.execute("ALTER TABLE bucket3_sync_state ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("bucket3_sync_state")
