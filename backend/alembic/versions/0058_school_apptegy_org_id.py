"""schools.apptegy_org_id - the Apptegy (Thrillshare) org id for a building
on that CMS (Collingswood, Oaklyn, Woodlynne), used in place of website_url
scraping for that platform's staff-directory/calendar APIs.

Revision ID: 0058
Revises: 0057
Create Date: 2026-09-27 00:00:00

"""
from typing import Sequence, Union

import sqlalchemy as sa
from alembic import op


revision: str = "0058"
down_revision: Union[str, None] = "0057"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("apptegy_org_id", sa.String(20), nullable=True))


def downgrade() -> None:
    op.drop_column("schools", "apptegy_org_id")
