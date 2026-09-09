"""district transportation department info

Revision ID: 0025
Revises: 0024
Create Date: 2026-09-09 14:30:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0025"
down_revision: Union[str, None] = "0024"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("transportation_url", sa.String(length=1000), nullable=True))
    op.add_column("districts", sa.Column("transportation_job_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(None, "districts", "scheduled_jobs", ["transportation_job_id"], ["id"], ondelete="SET NULL")
    op.create_table(
        "district_transportation",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("district_id", sa.String(length=36), sa.ForeignKey("districts.id", ondelete="CASCADE"), nullable=False, unique=True),
        sa.Column("office_phone", sa.String(length=50), nullable=True),
        sa.Column("office_fax", sa.String(length=50), nullable=True),
        sa.Column("office_hours", sa.String(length=200), nullable=True),
        sa.Column("office_address", sa.String(length=500), nullable=True),
        sa.Column("contacts", sa.JSON(), nullable=False),
        sa.Column("delay_policy", sa.String(), nullable=True),
        sa.Column("late_bus_policy", sa.String(), nullable=True),
        sa.Column("late_bus_contractors", sa.JSON(), nullable=False),
        sa.Column("bus_stop_change_procedure", sa.String(), nullable=True),
        sa.Column("bus_stop_change_deadline", sa.String(), nullable=True),
        sa.Column("bus_stop_change_form_url", sa.String(length=1000), nullable=True),
        sa.Column("lost_items_policy", sa.String(), nullable=True),
        sa.Column("main_url", sa.String(length=1000), nullable=True),
        sa.Column("late_bus_url", sa.String(length=1000), nullable=True),
        sa.Column("guidelines_url", sa.String(length=1000), nullable=True),
        sa.Column("lost_items_url", sa.String(length=1000), nullable=True),
        sa.Column("closing_info_url", sa.String(length=1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("district_transportation")
    op.drop_column("districts", "transportation_job_id")
    op.drop_column("districts", "transportation_url")
