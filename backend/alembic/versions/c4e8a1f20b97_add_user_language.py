"""add user language

Revision ID: c4e8a1f20b97
Revises: a7d3e9c41b58
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c4e8a1f20b97"
down_revision: str | Sequence[str] | None = "a7d3e9c41b58"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("language", sa.String(length=8), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "language")
