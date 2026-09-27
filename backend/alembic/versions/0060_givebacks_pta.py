"""Givebacks PTA page tracking - schools.givebacks_shortname/job_id and the
givebacks_blocks table (parallel to smore_blocks, keyed by school+page
rather than one newsletter, since a PTA's site has several pages).

Revision ID: 0060
Revises: 0059
Create Date: 2026-09-27 04:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0060"
down_revision: Union[str, None] = "0059"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("givebacks_shortname", sa.String(100), nullable=True))
    op.add_column(
        "schools",
        sa.Column("givebacks_job_id", sa.String(36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
    )
    op.create_table(
        "givebacks_blocks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("school_id", sa.String(36), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False, index=True),
        sa.Column("page_path", sa.String(500), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("block_type", sa.String(20), nullable=False),
        sa.Column("text_content", sa.String(), nullable=True),
        sa.Column("image_url", sa.String(1000), nullable=True),
        sa.Column("link_url", sa.String(1000), nullable=True),
        sa.Column("content_hash", sa.String(64), nullable=False),
        sa.Column("pending_vision_extraction", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("vision_extracted_text", sa.String(), nullable=True),
        sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("school_id", "page_path", "content_hash", name="uq_givebacks_block_school_page_hash"),
    )


def downgrade() -> None:
    op.drop_table("givebacks_blocks")
    op.drop_column("schools", "givebacks_job_id")
    op.drop_column("schools", "givebacks_shortname")
