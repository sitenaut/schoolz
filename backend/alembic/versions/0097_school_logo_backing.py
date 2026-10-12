"""Backing disc a school logo needs to stay visible in both themes

Districts publish transparent logos in white ink (for a dark header) or dark
ink (for a white one); on the wrong theme they render as nothing. This holds
the per-logo answer - none / light / dark - worked out from the image by
services/logo_backing.py during school_info.scan. NULL = not classified yet.

Revision ID: 0097
Revises: 0096
Create Date: 2026-10-11 22:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0097"
down_revision: Union[str, None] = "0096"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("logo_backing", sa.String(length=5), nullable=True))


def downgrade() -> None:
    op.drop_column("schools", "logo_backing")
