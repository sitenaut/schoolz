"""district_budgets + districts.state_code: the school page's budget section

`districts.state_code` is the state's own district id (NJDOE's 4-digit code),
which the state budget and aid files are keyed by; nullable, filled by the
budget import. `district_budgets` holds one budget year of state figures per
district. Additive: a new nullable column, a unique constraint that every
existing row (all null) already satisfies, and a new table nothing reads until
the code that writes it is deployed.

Revision ID: 0132
Revises: 0131
Create Date: 2026-10-24 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0132"
down_revision: str | None = "0131"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("state_code", sa.String(8), nullable=True))
    op.create_unique_constraint("uq_districts_state_code", "districts", ["state", "state_code"])
    op.create_table(
        "district_budgets",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("district_id", sa.String(36), sa.ForeignKey("districts.id", ondelete="CASCADE"), nullable=False),
        sa.Column("budget_year", sa.String(7), nullable=False),
        sa.Column("benefits_prior", sa.BigInteger(), nullable=True),
        sa.Column("benefits_budget", sa.BigInteger(), nullable=True),
        sa.Column("prior_basis", sa.String(20), nullable=False, server_default="revised"),
        sa.Column("formula_aid_change", sa.BigInteger(), nullable=True),
        sa.Column("levy_change_pct", sa.Float(), nullable=True),
        sa.Column("fund_balance_prior", sa.BigInteger(), nullable=True),
        sa.Column("fund_balance_budget", sa.BigInteger(), nullable=True),
        sa.Column("budget_report_url", sa.String(1000), nullable=True),
        sa.Column("aid_source_url", sa.String(1000), nullable=True),
        sa.Column("statements", sa.JSON(), nullable=False),
        sa.Column("source_commit", sa.String(40), nullable=False),
        sa.Column("imported_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("district_id", "budget_year", name="uq_district_budgets_year"),
    )
    op.create_index("ix_district_budgets_district_id", "district_budgets", ["district_id"])
    op.execute("ALTER TABLE district_budgets ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_district_budgets_district_id", table_name="district_budgets")
    op.drop_table("district_budgets")
    op.drop_constraint("uq_districts_state_code", "districts", type_="unique")
    op.drop_column("districts", "state_code")
