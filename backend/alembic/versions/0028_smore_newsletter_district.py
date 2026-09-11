"""smore_newsletters.district_id for district-wide (no single school) newsletters

Revision ID: 0028
Revises: 0027
Create Date: 2026-09-11 20:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0028"
down_revision: Union[str, None] = "0027"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("smore_newsletters", sa.Column("district_id", sa.String(length=36), nullable=True))
    op.create_foreign_key(
        "fk_smore_newsletters_district_id", "smore_newsletters", "districts", ["district_id"], ["id"], ondelete="SET NULL"
    )


def downgrade() -> None:
    op.drop_constraint("fk_smore_newsletters_district_id", "smore_newsletters", type_="foreignkey")
    op.drop_column("smore_newsletters", "district_id")
