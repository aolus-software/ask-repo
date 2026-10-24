"""add project content language

Revision ID: a3d5f7c9e1b2
Revises: e7c2b9d41f06
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a3d5f7c9e1b2"
down_revision: str | Sequence[str] | None = "e7c2b9d41f06"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "projects",
        sa.Column(
            "content_language",
            sa.String(length=8),
            nullable=False,
            server_default=sa.text("'en'"),
        ),
    )


def downgrade() -> None:
    op.drop_column("projects", "content_language")
