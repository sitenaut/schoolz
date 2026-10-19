"""email_scanners.link_kinds: which kinds of newsletter link a scanner keeps

An email scan now keeps only allowed newsletter links from a message
(services/email_links.py), never its body, subject, sender or snippet. Every
existing scanner gets ["smore"], the only kind it found before. Additive: one
column with a server default; safe before the code that reads it is deployed.

Revision ID: 0117
Revises: 0116
Create Date: 2026-10-19 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0117"
down_revision: str | None = "0116"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("email_scanners", sa.Column("link_kinds", sa.JSON(), server_default='["smore"]', nullable=False))


def downgrade() -> None:
    op.drop_column("email_scanners", "link_kinds")
