"""district vs school content item scoping

Revision ID: 0008
Revises: 0007
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0008"
down_revision: Union[str, None] = "0007"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("school_content_items", sa.Column("scope", sa.String(length=10), nullable=False, server_default="school"))
    op.add_column(
        "school_content_items",
        sa.Column("district_id", sa.String(length=36), sa.ForeignKey("districts.id", ondelete="CASCADE"), nullable=True),
    )
    op.alter_column("school_content_items", "school_id", nullable=True)
    op.create_index("ix_school_content_items_district_id", "school_content_items", ["district_id"])


def downgrade() -> None:
    op.drop_index("ix_school_content_items_district_id", table_name="school_content_items")
    op.alter_column("school_content_items", "school_id", nullable=False)
    op.drop_column("school_content_items", "district_id")
    op.drop_column("school_content_items", "scope")
