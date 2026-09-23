"""hs_class_pages: class years, class payments, grad-year filters

Revision ID: 0050
Revises: 0049
Create Date: 2026-09-23 13:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0050"
down_revision: Union[str, None] = "0049"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "school_class_years",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("school_id", sa.String(36), sa.ForeignKey("schools.id", ondelete="CASCADE"), nullable=False),
        sa.Column("grad_year", sa.Integer(), nullable=False),
        sa.Column("label", sa.String(50), nullable=True),
        sa.Column("grade_level_principal_staff_ids", sa.JSON(), nullable=True),
        sa.Column("advisor_staff_ids", sa.JSON(), nullable=True),
        sa.Column("instagram_url", sa.String(500), nullable=True),
        sa.Column("source_page_url", sa.String(500), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("school_id", "grad_year", name="uq_school_class_year"),
    )
    op.create_index("ix_school_class_years_school_id", "school_class_years", ["school_id"])
    op.execute("ALTER TABLE school_class_years ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "class_payments",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("school_class_year_id", sa.String(36), sa.ForeignKey("school_class_years.id", ondelete="CASCADE"), nullable=False),
        sa.Column("sequence", sa.Integer(), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("label", sa.String(200), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("window_opens_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("window_closes_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("methods", sa.JSON(), nullable=True),
        sa.Column("payschools_item_name", sa.String(200), nullable=True),
        sa.Column("refundable_until", sa.DateTime(timezone=True), nullable=True),
        sa.Column("notes", sa.String(1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("school_class_year_id", "sequence", name="uq_class_payment_sequence"),
    )
    op.create_index("ix_class_payments_school_class_year_id", "class_payments", ["school_class_year_id"])
    op.execute("ALTER TABLE class_payments ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "class_payment_ticks",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("class_payment_id", sa.String(36), sa.ForeignKey("class_payments.id", ondelete="CASCADE"), nullable=False),
        sa.Column("ticked_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("user_id", "class_payment_id", name="uq_class_payment_tick"),
    )
    op.create_index("ix_class_payment_ticks_user_id", "class_payment_ticks", ["user_id"])
    op.create_index("ix_class_payment_ticks_class_payment_id", "class_payment_ticks", ["class_payment_id"])
    op.execute("ALTER TABLE class_payment_ticks ENABLE ROW LEVEL SECURITY")

    op.add_column("school_content_items", sa.Column("applies_to_grad_years", sa.JSON(), nullable=True))

    op.add_column("schools", sa.Column("activities_calendar_ics_url", sa.String(500), nullable=True))
    op.add_column("schools", sa.Column("activities_calendar_job_id", sa.String(36), nullable=True))
    op.add_column("schools", sa.Column("announcements_doc_url", sa.String(500), nullable=True))
    op.add_column("schools", sa.Column("announcements_job_id", sa.String(36), nullable=True))
    op.add_column("schools", sa.Column("announcements_last_parsed_date", sa.String(10), nullable=True))
    op.add_column("schools", sa.Column("activities_site_url", sa.String(500), nullable=True))
    op.add_column("schools", sa.Column("activities_site_job_id", sa.String(36), nullable=True))
    op.create_foreign_key(
        "fk_schools_activities_calendar_job_id", "schools", "scheduled_jobs", ["activities_calendar_job_id"], ["id"], ondelete="SET NULL"
    )
    op.create_foreign_key("fk_schools_announcements_job_id", "schools", "scheduled_jobs", ["announcements_job_id"], ["id"], ondelete="SET NULL")
    op.create_foreign_key(
        "fk_schools_activities_site_job_id", "schools", "scheduled_jobs", ["activities_site_job_id"], ["id"], ondelete="SET NULL"
    )

    op.add_column("students", sa.Column("grad_year", sa.Integer(), nullable=True))


def downgrade() -> None:
    op.drop_column("students", "grad_year")

    op.drop_constraint("fk_schools_activities_site_job_id", "schools", type_="foreignkey")
    op.drop_constraint("fk_schools_announcements_job_id", "schools", type_="foreignkey")
    op.drop_constraint("fk_schools_activities_calendar_job_id", "schools", type_="foreignkey")
    op.drop_column("schools", "activities_site_job_id")
    op.drop_column("schools", "activities_site_url")
    op.drop_column("schools", "announcements_last_parsed_date")
    op.drop_column("schools", "announcements_job_id")
    op.drop_column("schools", "announcements_doc_url")
    op.drop_column("schools", "activities_calendar_job_id")
    op.drop_column("schools", "activities_calendar_ics_url")

    op.drop_column("school_content_items", "applies_to_grad_years")

    op.drop_index("ix_class_payment_ticks_class_payment_id", table_name="class_payment_ticks")
    op.drop_index("ix_class_payment_ticks_user_id", table_name="class_payment_ticks")
    op.drop_table("class_payment_ticks")

    op.drop_index("ix_class_payments_school_class_year_id", table_name="class_payments")
    op.drop_table("class_payments")

    op.drop_index("ix_school_class_years_school_id", table_name="school_class_years")
    op.drop_table("school_class_years")
