"""smore_newsletters.source_type - "smore" (default) or "virtual_backpack",
so a non-Smore bulletin-board page (Audubon Public Schools' "virtual
backpack") can reuse the exact same newsletter/block/extraction machinery
while still routing to its own scan job kind (virtual_backpack.scan) and
parser (services/backpack_parser.py).

Revision ID: 0067
Revises: 0066
Create Date: 2026-09-29 04:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0067"
down_revision: Union[str, None] = "0066"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "smore_newsletters",
        sa.Column("source_type", sa.String(20), nullable=False, server_default="smore"),
    )
    op.alter_column("smore_newsletters", "source_type", server_default=None)


def downgrade() -> None:
    op.drop_column("smore_newsletters", "source_type")
