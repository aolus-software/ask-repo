"""add refresh token device

Revision ID: d4a9e6b27c15
Revises: c3f8a1d05e72
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "d4a9e6b27c15"
down_revision: str | Sequence[str] | None = "c3f8a1d05e72"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("refresh_tokens", sa.Column("user_agent", sa.String(length=255), nullable=True))
    op.add_column("refresh_tokens", sa.Column("ip_address", sa.String(length=45), nullable=True))


def downgrade() -> None:
    op.drop_column("refresh_tokens", "ip_address")
    op.drop_column("refresh_tokens", "user_agent")
