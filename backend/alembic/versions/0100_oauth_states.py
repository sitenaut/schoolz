"""Gmail connect: make each OAuth state single-use

routers/gmail.py records the nonce of every state it hands out; the callback
deletes the row to use it, so a captured state can't be replayed within its
ten minutes. Rows past expires_at are pruned when the next state is made.

Revision ID: 0100
Revises: 0099
Create Date: 2026-10-15 14:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op

revision: str = "0100"
down_revision: Union[str, None] = "0099"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "oauth_states",
        sa.Column("nonce", sa.String(length=64), primary_key=True),
        sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id", ondelete="CASCADE"), nullable=False),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
    )


def downgrade() -> None:
    op.drop_table("oauth_states")  # destructive-ok: only outstanding ten-minute connect attempts
