"""child_grade_entries.graded_at + listed_in: Genesis assignments not graded yet

schoolz now reads Genesis's List Assignments page, which lists every
assignment, graded or not. The family feed reported an entry as news when
schoolz first saw it, so an assignment listed before it's graded needs its own
"first seen graded" time. listed_in records the List Assignments range that
listed it, so a later read of that range can drop one never graded that's gone.

Additive: two nullable columns. Every row so far came from Course Summary, and
one that already shows a score or a mark was news when first seen, so
graded_at starts as first_seen_at for those.

Revision ID: 0150
Revises: 0149
Create Date: 2026-11-10 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0150"
down_revision: str | None = "0149"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("child_grade_entries", sa.Column("graded_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("child_grade_entries", sa.Column("listed_in", sa.String(10), nullable=True))
    op.execute(
        "UPDATE child_grade_entries SET graded_at = first_seen_at "
        "WHERE score_earned IS NOT NULL OR percent IS NOT NULL OR status IS NOT NULL"
    )


def downgrade() -> None:
    op.drop_column("child_grade_entries", "listed_in")
    op.drop_column("child_grade_entries", "graded_at")
