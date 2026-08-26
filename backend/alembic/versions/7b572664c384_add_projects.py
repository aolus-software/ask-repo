"""add projects

Revision ID: 7b572664c384
Revises: 0001
Create Date: 2026-08-26 10:52:48.031703

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "7b572664c384"
down_revision = "0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projects",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("repo_url", sa.String(length=2048), nullable=False),
        sa.Column("branch", sa.String(length=255), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("error", sa.String(length=4096), nullable=True),
        sa.Column("last_indexed_commit", sa.String(length=40), nullable=True),
        sa.Column("file_count", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=True),
        sa.Column("encrypted_pat", sa.LargeBinary(), nullable=True),
        sa.Column("lease_owner", sa.String(length=255), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reindex_in_progress", sa.Boolean(), nullable=False),
        sa.Column("active_generation", sa.BigInteger(), nullable=False),
        sa.Column("embedding_collection", sa.String(length=255), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(["created_by"], ["users.id"], name="fk_projects_created_by_users"),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
    )
    op.create_index("ix_projects_created_by", "projects", ["created_by"])
    op.create_index("ix_projects_status", "projects", ["status"])
    # Used by the reconcile sweep, which scans for leases that have expired on a
    # given status (e.g. stuck `cloning`/`indexing` rows after a worker restart).
    op.create_index(
        "ix_projects_status_lease_expires_at",
        "projects",
        ["status", "lease_expires_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_projects_status_lease_expires_at", table_name="projects")
    op.drop_index("ix_projects_status", table_name="projects")
    op.drop_index("ix_projects_created_by", table_name="projects")
    op.drop_table("projects")
