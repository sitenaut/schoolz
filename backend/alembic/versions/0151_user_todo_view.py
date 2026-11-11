"""users.todo_view: which To do list a person last picked in Gradez

Gradez's To do tab shows either what's next (today and the next school day)
or the whole week. The choice is the person's own, so it follows their account
across devices rather than living in one browser.

Additive: one nullable column. Null means never picked, and the page then
opens on what's next for a student and the whole week for a guardian.

Revision ID: 0151
Revises: 0150
Create Date: 2026-11-10 00:00:00
"""
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0151"
down_revision: str | None = "0150"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("todo_view", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "todo_view")
