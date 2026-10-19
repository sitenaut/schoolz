"""Purge what email scans stored of messages before 0117

Since 0117 an email scan keeps only allowed newsletter links
(services/email_links.py). Rows written before then still hold the message's
body, subject, sender and Gmail snippet; nothing serves them, and this blanks
them. The rows themselves stay (the match ledger is what stops a message being
processed twice; a message's found links stay with it).

Revision ID: 0118
Revises: 0117
Create Date: 2026-10-19 00:00:00
"""
from collections.abc import Sequence

from alembic import op

revision: str = "0118"
down_revision: str | None = "0117"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # destructive-ok: blanks stored email text the owner asked to purge (the feature was unused); on-demand backup.yml run 39277336512 taken first
    op.execute("UPDATE school_email_messages SET body_text = NULL, subject = NULL, sender = NULL "
               "WHERE body_text IS NOT NULL OR subject IS NOT NULL OR sender IS NOT NULL")
    op.execute("UPDATE email_scanner_matches SET snippet = NULL, subject = NULL, sender = NULL "
               "WHERE snippet IS NOT NULL OR subject IS NOT NULL OR sender IS NOT NULL")


def downgrade() -> None:
    # Nothing to restore: the text is gone (the backup above holds it).
    pass
