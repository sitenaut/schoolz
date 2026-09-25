"""app_settings: admin-editable runtime settings (first use: chatbot provider/model)

Revision ID: 0053
Revises: 0052
Create Date: 2026-09-25 17:00:00

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision: str = "0053"
down_revision: Union[str, None] = "0052"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "app_settings",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", postgresql.JSONB(), nullable=False, server_default=sa.text("'{}'::jsonb")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_by_user_id", sa.String(36), sa.ForeignKey("users.id", ondelete="SET NULL"), nullable=True),
    )
    # Every table here has RLS on with no policies (nothing goes through
    # Supabase's Data API) - see CLAUDE.md, "Prod and deployment".
    op.execute("ALTER TABLE app_settings ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("app_settings")
