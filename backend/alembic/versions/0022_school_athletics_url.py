"""school athletics_url + seed ArbiterLive links for the high schools

Revision ID: 0022
Revises: 0021
Create Date: 2026-09-09 00:10:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0022"
down_revision: Union[str, None] = "0021"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("athletics_url", sa.String(length=500), nullable=True))
    # ArbiterLive entity ids confirmed 2026-09-08: West 4058, East 4057.
    for domain, entity in (("west.chclc.org", 4058), ("east.chclc.org", 4057)):
        op.execute(f"UPDATE schools SET athletics_url = 'https://www.arbiterlive.com/Teams?entityId={entity}' WHERE website_url LIKE '%{domain}%'")


def downgrade() -> None:
    op.drop_column("schools", "athletics_url")
