"""district_budgets.state_aid and idea_grant: where a district's aid comes from

The budget page showed only the change in state aid. These hold both years
of K-12 aid by category (and whether the state's limit on a year's change
held it), preschool aid, and the federal special education grant (IDEA), each
from the state's own files. Additive: two nullable columns the previous
release never reads.

Revision ID: 0136
Revises: 0135
Create Date: 2026-10-26 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0136"
down_revision: str | None = "0135"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("district_budgets", sa.Column("state_aid", sa.JSON(), nullable=True))
    op.add_column("district_budgets", sa.Column("idea_grant", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("district_budgets", "idea_grant")
    op.drop_column("district_budgets", "state_aid")
