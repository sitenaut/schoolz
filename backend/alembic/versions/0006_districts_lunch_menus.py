"""districts, school type, lunch menus

Revision ID: 0006
Revises: 0005
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0006"
down_revision: Union[str, None] = "0005"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "districts",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("website_url", sa.String(length=500), nullable=True),
        sa.Column("food_services_menu_url", sa.String(length=1000), nullable=True),
        sa.Column("scheduled_job_id", sa.String(length=36), sa.ForeignKey("scheduled_jobs.id", ondelete="SET NULL"), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("name", name="uq_districts_name"),
    )

    op.add_column("schools", sa.Column("district_id", sa.String(length=36), sa.ForeignKey("districts.id", ondelete="SET NULL"), nullable=True))
    op.add_column("schools", sa.Column("school_type", sa.String(length=20), nullable=True))

    op.create_table(
        "lunch_menus",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("district_id", sa.String(length=36), sa.ForeignKey("districts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("school_type", sa.String(length=20), nullable=False),
        sa.Column("meal_type", sa.String(length=20), nullable=False),
        sa.Column("period_label", sa.String(length=50), nullable=False),
        sa.Column("source_pdf_url", sa.String(length=1000), nullable=False),
        sa.Column("parsed_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("district_id", "school_type", "meal_type", "source_pdf_url", name="uq_lunch_menu_source"),
    )

    op.create_table(
        "lunch_menu_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("lunch_menu_id", sa.String(length=36), sa.ForeignKey("lunch_menus.id", ondelete="CASCADE"), nullable=False),
        sa.Column("menu_date", sa.DateTime(timezone=True), nullable=False),
        sa.Column("description", sa.String(length=500), nullable=False),
        sa.Column("notes", sa.String(length=500), nullable=True),
        sa.UniqueConstraint("lunch_menu_id", "menu_date", name="uq_lunch_menu_item_date"),
    )
    op.create_index("ix_lunch_menu_items_lunch_menu_id", "lunch_menu_items", ["lunch_menu_id"])


def downgrade() -> None:
    op.drop_table("lunch_menu_items")
    op.drop_table("lunch_menus")
    op.drop_column("schools", "school_type")
    op.drop_column("schools", "district_id")
    op.drop_table("districts")
