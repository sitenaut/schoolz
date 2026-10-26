"""district_transportation.office_email: the office's own address

Some departments ask to be emailed rather than called (Voorhees, Eastern
Regional: "The best means of contact is via email to ..."), so the address
is the office's contact, not a person on the staff list. Additive: one
nullable column the previous release never reads.

Revision ID: 0135
Revises: 0134
Create Date: 2026-10-26 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0135"
down_revision: str | None = "0134"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("district_transportation", sa.Column("office_email", sa.String(320), nullable=True))


def downgrade() -> None:
    op.drop_column("district_transportation", "office_email")
