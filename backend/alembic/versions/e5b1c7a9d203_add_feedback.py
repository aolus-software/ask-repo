"""add feedback

Revision ID: e5b1c7a9d203
Revises: d4a9e6b27c15
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "e5b1c7a9d203"
down_revision: str | Sequence[str] | None = "d4a9e6b27c15"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "feedback",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("user_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("target_type", sa.String(length=32), nullable=False),
        sa.Column("target_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature", sa.String(length=32), nullable=False),
        sa.Column("rating", sa.String(length=8), nullable=False),
        sa.Column(
            "reason_codes",
            postgresql.ARRAY(sa.String(length=32)),
            nullable=False,
            server_default=sa.text("'{}'"),
        ),
        sa.Column("note", sa.String(length=500), nullable=True),
        sa.Column("prompt_version", sa.String(length=16), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_feedback_user_id_users"),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name="fk_feedback_project_id_projects"
        ),
        sa.CheckConstraint("rating IN ('up', 'down')", name="rating"),
        sa.CheckConstraint(
            "rating = 'up' OR cardinality(reason_codes) > 0", name="down_has_reason"
        ),
    )
    op.create_index(
        "uq_feedback_user_target",
        "feedback",
        ["user_id", "target_type", "target_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index("ix_feedback_project_id_created_at", "feedback", ["project_id", "created_at"])
    op.create_index("ix_feedback_feature_created_at", "feedback", ["feature", "created_at"])
    op.create_index("ix_feedback_target", "feedback", ["target_type", "target_id"])


def downgrade() -> None:
    op.drop_index("ix_feedback_target", table_name="feedback")
    op.drop_index("ix_feedback_feature_created_at", table_name="feedback")
    op.drop_index("ix_feedback_project_id_created_at", table_name="feedback")
    op.drop_index("uq_feedback_user_target", table_name="feedback")
    op.drop_table("feedback")
