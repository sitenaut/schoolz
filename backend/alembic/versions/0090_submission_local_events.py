"""Let a reviewed submission item be published as a local event

A draft item gains a third scope, "local", for community events that belong on
/local rather than a school calendar. It needs a venue (the local-events table
has one, a school item doesn't), hand-picked category tags, and a pointer to the LocalEvent it became.

Revision ID: 0090
Revises: 0089
Create Date: 2026-10-09 18:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql


revision: str = "0090"
down_revision: Union[str, None] = "0089"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("community_submission_items", sa.Column("venue_name", sa.String(200), nullable=True))
    op.add_column("community_submission_items", sa.Column("venue_address", sa.String(300), nullable=True))
    op.add_column(
        "community_submission_items",
        sa.Column("local_categories", postgresql.ARRAY(sa.Text()), nullable=False, server_default="{}"),
    )
    op.add_column(
        "community_submission_items",
        sa.Column("local_event_id", sa.String(36), sa.ForeignKey("local_events.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("community_submission_items", "local_event_id")
    op.drop_column("community_submission_items", "local_categories")
    op.drop_column("community_submission_items", "venue_address")
    op.drop_column("community_submission_items", "venue_name")
