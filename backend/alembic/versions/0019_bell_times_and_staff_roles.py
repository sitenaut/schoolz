"""school bell times and staff roles

Revision ID: 0019
Revises: 0018
Create Date: 2026-09-08 23:40:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


revision: str = "0019"
down_revision: Union[str, None] = "0018"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column("schools", sa.Column("start_time", sa.String(length=20), nullable=True))
    op.add_column("schools", sa.Column("end_time", sa.String(length=20), nullable=True))
    op.add_column("schools", sa.Column("early_dismissal_time", sa.String(length=20), nullable=True))
    op.add_column("staff_members", sa.Column("role", sa.String(length=30), nullable=True))
    op.create_index(op.f("ix_staff_members_role"), "staff_members", ["role"], unique=False)
    # Backfill with the same keyword rules as services/staff_roles.py so
    # already-scanned rosters get roles without waiting for the next scan.
    op.execute(
        """
        UPDATE staff_members SET role = CASE
            WHEN title ~* '\\m(assistant|vice)\\s+principal\\M' THEN 'assistant_principal'
            WHEN title ~* '\\mprincipal\\M' THEN 'principal'
            WHEN title ~* '\\mnurse\\M' THEN 'nurse'
            WHEN title ~* '\\m(counselor|counsellor|guidance)\\M' THEN 'counselor'
            WHEN title ~* '\\msacc\\M' THEN 'sacc'
            WHEN title ~* '\\m(secretary|office manager|administrative assistant|main office)\\M' THEN 'secretary'
            WHEN title ~* '\\msocial worker\\M' THEN 'social_worker'
            WHEN title ~* '\\mpsychologist\\M' THEN 'psychologist'
            ELSE NULL END
        WHERE title IS NOT NULL
        """
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_staff_members_role"), table_name="staff_members")
    op.drop_column("staff_members", "role")
    op.drop_column("schools", "early_dismissal_time")
    op.drop_column("schools", "end_time")
    op.drop_column("schools", "start_time")
