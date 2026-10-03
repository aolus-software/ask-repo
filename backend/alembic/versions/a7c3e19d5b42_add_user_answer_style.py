"""add user answer style

Revision ID: a7c3e19d5b42
Revises: e5b1c7a9d203
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7c3e19d5b42"
down_revision: str | Sequence[str] | None = "e5b1c7a9d203"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("users", sa.Column("answer_detail", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("answer_familiarity", sa.String(length=16), nullable=True))
    op.add_column("users", sa.Column("answer_format", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("users", "answer_format")
    op.drop_column("users", "answer_familiarity")
    op.drop_column("users", "answer_detail")
