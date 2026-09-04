"""Add the QA Checklist tables and drop qa_pairs.

M4 was re-scoped: the shipped `qa_pairs` table was a regression set for AskRepo's own
retrieval, and this milestone replaces it with a test plan for the *indexed*
application (spec 0). The two are different products that shared a word.

**The drop is not reversible with data.** `downgrade()` recreates `qa_pairs` empty.
There is deliberately no data migration into `checklist_items`: a saved
question-and-answer is not a test case, and mechanically reshaping one into the other
would produce rows whose `expected_result` is a paragraph of prose about the codebase.

`checklist_modules.last_job_id` is not in spec 3.1's column list. It is required by
4.5, which says the lease works exactly as `ProjectRepository.claim` does -- and that
claim gates on `last_job_id` to tell a redelivery of a finished job from a new request.

Revision ID: 53c8d09a5af3
Revises: 7115e8d10243
Create Date: 2026-09-02 14:23:05.533463

"""

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision = "53c8d09a5af3"
down_revision = "7115e8d10243"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "checklist_modules",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source_path", sa.String(length=512), nullable=False),
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
            ["project_id"], ["projects.id"], name=op.f("fk_checklist_modules_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_checklist_modules_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_modules")),
    )
    op.create_index("ix_checklist_modules_created_by", "checklist_modules", ["created_by"])
    op.create_index(
        "ix_checklist_modules_project_id_created_at",
        "checklist_modules",
        ["project_id", "created_at"],
    )

    op.create_table(
        "checklist_messages",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            ["module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_checklist_messages_module_id_checklist_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_checklist_messages_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_messages")),
    )
    op.create_index("ix_checklist_messages_created_by", "checklist_messages", ["created_by"])
    op.create_index(
        "ix_checklist_messages_module_id_created_at",
        "checklist_messages",
        ["module_id", "created_at"],
    )

    op.create_table(
        "checklist_items",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("feature", sa.String(length=120), nullable=False),
        sa.Column("test_name", sa.Text(), nullable=False),
        sa.Column("expected_result", sa.Text(), nullable=False),
        sa.Column("current_result", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_checklist_items_module_id_checklist_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_checklist_items_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_checklist_items_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=op.f("fk_checklist_items_reviewed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_items")),
    )
    op.create_index("ix_checklist_items_created_by", "checklist_items", ["created_by"])
    op.create_index("ix_checklist_items_status", "checklist_items", ["status"])
    op.create_index(
        "ix_checklist_items_module_id_feature_position",
        "checklist_items",
        ["module_id", "feature", "position"],
    )
    op.create_index(
        "ix_checklist_items_project_id_status", "checklist_items", ["project_id", "status"]
    )

    op.create_table(
        "checklist_change_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module_id", postgresql.UUID(as_uuid=True), nullable=False),
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
            ["module_id"],
            ["checklist_modules.id"],
            name=op.f("fk_checklist_change_sets_module_id_checklist_modules"),
        ),
        sa.ForeignKeyConstraint(
            ["message_id"],
            ["checklist_messages.id"],
            name=op.f("fk_checklist_change_sets_message_id_checklist_messages"),
        ),
        sa.ForeignKeyConstraint(
            ["resolved_by"], ["users.id"], name=op.f("fk_checklist_change_sets_resolved_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_checklist_change_sets_created_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_checklist_change_sets")),
    )
    op.create_index("ix_checklist_change_sets_created_by", "checklist_change_sets", ["created_by"])
    op.create_index(
        "ix_checklist_change_sets_module_id_status",
        "checklist_change_sets",
        ["module_id", "status"],
    )

    op.drop_index("ix_qa_pairs_tags", table_name="qa_pairs")
    op.drop_index("ix_qa_pairs_project_id_created_at", table_name="qa_pairs")
    op.drop_table("qa_pairs")


def downgrade() -> None:
    """Reverses the schema. It cannot reverse the data: `qa_pairs` comes back empty."""
    op.create_table(
        "qa_pairs",
        sa.Column("id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("module", sa.String(length=120), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("answer", sa.Text(), nullable=True),
        sa.Column("reference_answer", sa.Text(), nullable=True),
        sa.Column("citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("tags", postgresql.ARRAY(sa.String()), server_default="{}", nullable=False),
        sa.Column("source", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("reviewed_by", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("reviewed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("model", sa.String(length=255), nullable=True),
        sa.Column("eval_score", sa.Float(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("pending_answer", sa.Text(), nullable=True),
        sa.Column("pending_citations", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("pending_model", sa.String(length=255), nullable=True),
        sa.Column("pending_finish_reason", sa.String(length=32), nullable=True),
        sa.Column("pending_run_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_qa_pairs_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_qa_pairs_created_by_users")
        ),
        sa.ForeignKeyConstraint(
            ["reviewed_by"], ["users.id"], name=op.f("fk_qa_pairs_reviewed_by_users")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_qa_pairs")),
    )
    op.create_index(op.f("ix_qa_pairs_created_by"), "qa_pairs", ["created_by"], unique=False)
    op.create_index("ix_qa_pairs_project_id_created_at", "qa_pairs", ["project_id", "created_at"])
    op.create_index(op.f("ix_qa_pairs_status"), "qa_pairs", ["status"], unique=False)
    op.create_index("ix_qa_pairs_tags", "qa_pairs", ["tags"], postgresql_using="gin")

    op.drop_table("checklist_change_sets")
    op.drop_table("checklist_items")
    op.drop_table("checklist_messages")
    op.drop_table("checklist_modules")
