"""Remember which contact page text a school's contact-page staff came from

The roster scan reads a hand-typed "Contact Us" page with a model call when
the directory has no titles. Storing the page text's hash lets it skip that
call while the page is unchanged.

Revision ID: 0091
Revises: 0090
Create Date: 2026-10-10 09:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0091"
down_revision: Union[str, None] = "0090"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("contact_page_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("schools", "contact_page_hash")
