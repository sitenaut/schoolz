"""state_districts + statewide district_budgets: the /budgets section

`state_districts` is the state's own list of school districts (every NJ
district that files a budget, not only the ones schoolz tracks), each with a
permanent slug for its /budgets page. A budget row now belongs to a state
district, and also to one of our districts when we track it, so
`district_budgets.district_id` becomes nullable. The new figure columns are
nullable. Additive: a new table, new nullable columns, a unique constraint
every existing row (all null) already satisfies, and a NOT NULL relaxed;
the previous release's code writes and reads exactly what it did before.

Revision ID: 0133
Revises: 0132
Create Date: 2026-10-25 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0133"
down_revision: str | None = "0132"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "state_districts",
        sa.Column("id", sa.String(36), primary_key=True),
        sa.Column("state", sa.String(2), nullable=False, server_default="NJ"),
        sa.Column("state_code", sa.String(8), nullable=False),
        sa.Column("name", sa.String(255), nullable=False),
        sa.Column("county", sa.String(100), nullable=True),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.UniqueConstraint("state", "state_code", name="uq_state_districts_code"),
        sa.UniqueConstraint("slug", name="uq_state_districts_slug"),
    )
    op.execute("ALTER TABLE state_districts ENABLE ROW LEVEL SECURITY")

    op.add_column(
        "district_budgets",
        sa.Column("state_district_id", sa.String(36), sa.ForeignKey("state_districts.id", ondelete="CASCADE"), nullable=True),
    )
    op.create_index("ix_district_budgets_state_district_id", "district_budgets", ["state_district_id"])
    op.create_unique_constraint("uq_district_budgets_state_year", "district_budgets", ["state_district_id", "budget_year"])
    op.alter_column("district_budgets", "district_id", existing_type=sa.String(36), nullable=True)
    for name in ("levy_prior", "levy_budget", "other_spending_prior", "other_spending_budget"):
        op.add_column("district_budgets", sa.Column(name, sa.BigInteger(), nullable=True))
    op.add_column("district_budgets", sa.Column("comparable", sa.Boolean(), nullable=True))
    op.add_column("district_budgets", sa.Column("health_costs", sa.JSON(), nullable=True))
    op.add_column("district_budgets", sa.Column("staffing", sa.JSON(), nullable=True))


def downgrade() -> None:
    for name in ("staffing", "health_costs", "comparable", "other_spending_budget", "other_spending_prior", "levy_budget", "levy_prior"):
        op.drop_column("district_budgets", name)
    op.drop_constraint("uq_district_budgets_state_year", "district_budgets", type_="unique")
    op.drop_index("ix_district_budgets_state_district_id", table_name="district_budgets")
    op.drop_column("district_budgets", "state_district_id")
    op.drop_table("state_districts")
