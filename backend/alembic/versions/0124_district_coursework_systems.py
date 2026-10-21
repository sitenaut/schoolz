"""districts.uses_google_classroom + districts.genesis_url

Which of a district's systems Backpack Capture can bring into schoolz, so My
family explains homework and grades only for children whose school has them.
Additive: two new columns (one with a server default), then Cherry Hill's
values filled in only where still unset.

Revision ID: 0124
Revises: 0123
Create Date: 2026-10-21 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0124"
down_revision: str | None = "0123"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("districts", sa.Column("uses_google_classroom", sa.Boolean(), nullable=False, server_default=sa.false()))
    op.add_column("districts", sa.Column("genesis_url", sa.String(500), nullable=True))
    # The one district Backpack Capture has been used with end to end.
    op.execute(
        "UPDATE districts SET uses_google_classroom = true, genesis_url = 'https://parents.chclc.org/genesis/parents' "
        "WHERE state = 'NJ' AND name = 'Cherry Hill Public Schools' AND genesis_url IS NULL"
    )


def downgrade() -> None:
    op.drop_column("districts", "genesis_url")
    op.drop_column("districts", "uses_google_classroom")
