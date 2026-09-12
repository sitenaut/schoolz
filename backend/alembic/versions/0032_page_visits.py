"""page_visits - aggregate daily visit counters for the public pages

Revision ID: 0032
Revises: 0031
Create Date: 2026-09-12 15:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0032"
down_revision: Union[str, None] = "0031"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "page_visits",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("day", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=100), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("day", "path", "source", name="uq_page_visits_day_path_source"),
    )
    op.create_index("ix_page_visits_day", "page_visits", ["day"])


def downgrade() -> None:
    op.drop_index("ix_page_visits_day", table_name="page_visits")
    op.drop_table("page_visits")
