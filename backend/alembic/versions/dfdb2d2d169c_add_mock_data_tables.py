"""Add the QA Mock Data Generator tables.

Four tables mirroring `checklist_modules`/`checklist_items`/`checklist_change_sets`/
`checklist_messages` for a second content type. `mock_data_datasets` carries its own
status and generation lease rather than reusing `checklist_modules`' columns, because a
module's checklist and its mock dataset generate, review, and fail independently.

Revision ID: dfdb2d2d169c
Revises: 8c1f4e7ab203
Create Date: 2026-09-05 00:00:00.000000

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "dfdb2d2d169c"
down_revision = "8c1f4e7ab203"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "mock_data_datasets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checklist_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("indexed_generation", sa.Integer(), nullable=True),
        sa.Column("last_generated_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["checklist_module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_mock_data_datasets_checklist_module_id_checklist_modules"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_data_datasets")),
        sa.UniqueConstraint(
            "checklist_module_id", name=op.f("uq_mock_data_datasets_checklist_module_id")
        ),
    )

    op.create_table(
        "mock_data_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checklist_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("finish_reason", sa.String(length=32), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["checklist_module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_mock_data_messages_checklist_module_id_checklist_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_mock_data_messages_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_data_messages")),
    )
    op.create_index("ix_mock_data_messages_created_by", "mock_data_messages", ["created_by"])
    op.create_index(
        "ix_mock_data_messages_module_id_created_at",
        "mock_data_messages",
        ["checklist_module_id", "created_at"],
    )

    op.create_table(
        "mock_data_records",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checklist_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("fields", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["checklist_module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_mock_data_records_checklist_module_id_checklist_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_mock_data_records_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_data_records")),
    )
    op.create_index("ix_mock_data_records_created_by", "mock_data_records", ["created_by"])
    op.create_index(
        "ix_mock_data_records_module_id_created_at",
        "mock_data_records",
        ["checklist_module_id", "created_at"],
    )

    op.create_table(
        "mock_data_change_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("checklist_module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("origin", sa.String(length=16), nullable=False),
        sa.Column("message_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("operations", postgresql.JSONB(astext_type=sa.Text()), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("resolved_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["checklist_module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_mock_data_change_sets_checklist_module_id_checklist_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["mock_data_messages.id"],
            name=op.f("fk_mock_data_change_sets_message_id_mock_data_messages"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name=op.f("fk_mock_data_change_sets_resolved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_mock_data_change_sets_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_mock_data_change_sets")),
    )
    op.create_index(
        "ix_mock_data_change_sets_created_by", "mock_data_change_sets", ["created_by"]
    )
    op.create_index(
        "ix_mock_data_change_sets_module_id_status",
        "mock_data_change_sets",
        ["checklist_module_id", "status"],
    )


def downgrade() -> None:
    op.drop_table("mock_data_change_sets")
    op.drop_table("mock_data_records")
    op.drop_table("mock_data_messages")
    op.drop_table("mock_data_datasets")
