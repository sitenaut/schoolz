"""link students to schools

Revision ID: 0005
Revises: 0004
Create Date: 2026-09-08

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa

revision: str = "0005"
down_revision: Union[str, None] = "0004"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "students",
        sa.Column("school_id", sa.String(length=36), sa.ForeignKey("schools.id", ondelete="SET NULL"), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("students", "school_id")
