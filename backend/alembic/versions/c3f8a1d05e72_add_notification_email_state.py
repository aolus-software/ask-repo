"""add notification email state

Revision ID: c3f8a1d05e72
Revises: b7d2e4f19a06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c3f8a1d05e72"
down_revision: str | Sequence[str] | None = "b7d2e4f19a06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("notifications", sa.Column("email_state", sa.String(length=16), nullable=True))
    op.add_column(
        "notifications",
        sa.Column("email_attempts", sa.SmallInteger(), server_default=sa.text("0"), nullable=False),
    )
    op.add_column(
        "notifications", sa.Column("email_claimed_until", sa.DateTime(timezone=True), nullable=True)
    )
    op.add_column(
        "notifications", sa.Column("email_sent_at", sa.DateTime(timezone=True), nullable=True)
    )
    op.create_index(
        "ix_notifications_email_pending",
        "notifications",
        ["created_at"],
        unique=False,
        postgresql_where=sa.text("email_state = 'pending'"),
    )


def downgrade() -> None:
    op.drop_index("ix_notifications_email_pending", table_name="notifications")
    op.drop_column("notifications", "email_sent_at")
    op.drop_column("notifications", "email_claimed_until")
    op.drop_column("notifications", "email_attempts")
    op.drop_column("notifications", "email_state")
