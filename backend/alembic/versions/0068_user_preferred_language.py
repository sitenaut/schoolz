"""users.preferred_language - the language a signed-in person chose ("es"),
so the choice follows them to another device. Null means never chosen
(the site stays in whatever language the URL/browser gave them).

Revision ID: 0068
Revises: 0067
Create Date: 2026-09-29 12:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0068"
down_revision: Union[str, None] = "0067"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("users", sa.Column("preferred_language", sa.String(8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "preferred_language")
