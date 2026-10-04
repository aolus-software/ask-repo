"""add eval tables

Revision ID: b3e81f4c2a90
Revises: a7c3e19d5b42
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "b3e81f4c2a90"
down_revision: str | Sequence[str] | None = "a7c3e19d5b42"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "eval_sets",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("source_path", sa.String(length=1024), nullable=True),
        sa.Column("requested_count", sa.SmallInteger(), nullable=False),
        sa.Column("mix", sa.String(length=16), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pair_count", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("indexed_generation", sa.Integer(), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_eval_sets_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_eval_sets_created_by_users")
        ),
    )
    op.create_index("ix_eval_sets_project_id", "eval_sets", ["project_id"])

    op.create_table(
        "eval_pairs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("position", sa.SmallInteger(), nullable=False),
        sa.Column("question_type", sa.String(length=16), nullable=False),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("reference_answer", sa.Text(), nullable=False),
        sa.Column("source_file", sa.String(length=1024), nullable=False),
        sa.Column("start_line", sa.Integer(), nullable=False),
        sa.Column("end_line", sa.Integer(), nullable=False),
        sa.Column("excluded_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["set_id"], ["eval_sets.id"], name=op.f("fk_eval_pairs_set_id_eval_sets")
        ),
    )
    op.create_index("ix_eval_pairs_set_id", "eval_pairs", ["set_id"])

    op.create_table(
        "eval_runs",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("set_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.String(length=12), nullable=True),
        sa.Column("chat_provider", sa.String(length=64), nullable=True),
        sa.Column("chat_model", sa.String(length=255), nullable=True),
        sa.Column("judge_model", sa.String(length=255), nullable=True),
        sa.Column("embedding_model", sa.String(length=255), nullable=True),
        sa.Column("project_generation", sa.Integer(), nullable=True),
        sa.Column("pairs_answered", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("hits", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("correct", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("partial", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("wrong", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("errors", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("lease_owner", sa.String(length=64), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_job_id", postgresql.UUID(as_uuid=True), nullable=True),
        sa.Column("created_by", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["set_id"], ["eval_sets.id"], name=op.f("fk_eval_runs_set_id_eval_sets")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"], ["projects.id"], name=op.f("fk_eval_runs_project_id_projects")
        ),
        sa.ForeignKeyConstraint(
            ["created_by"], ["users.id"], name=op.f("fk_eval_runs_created_by_users")
        ),
    )
    op.create_index("ix_eval_runs_set_id", "eval_runs", ["set_id"])
    op.create_index("ix_eval_runs_project_id", "eval_runs", ["project_id"])

    op.create_table(
        "eval_results",
        sa.Column("id", postgresql.UUID(as_uuid=True), primary_key=True),
        sa.Column("run_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("pair_id", postgresql.UUID(as_uuid=True), nullable=False),
        sa.Column("retrieval_hit", sa.Boolean(), nullable=False),
        sa.Column("verdict", sa.String(length=16), nullable=False),
        sa.Column("judge_reason", sa.String(length=500), nullable=True),
        sa.Column("answer", sa.Text(), nullable=False),
        sa.Column(
            "grounding_warnings",
            postgresql.JSONB(),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("retrieval_attempts", sa.SmallInteger(), nullable=False, server_default="0"),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["run_id"], ["eval_runs.id"], name=op.f("fk_eval_results_run_id_eval_runs")
        ),
        sa.ForeignKeyConstraint(
            ["pair_id"], ["eval_pairs.id"], name=op.f("fk_eval_results_pair_id_eval_pairs")
        ),
    )
    op.create_index("ix_eval_results_run_id", "eval_results", ["run_id"])
    op.create_index(
        "uq_eval_results_run_pair",
        "eval_results",
        ["run_id", "pair_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_eval_results_run_pair", table_name="eval_results")
    op.drop_index("ix_eval_results_run_id", table_name="eval_results")
    op.drop_table("eval_results")
    op.drop_index("ix_eval_runs_project_id", table_name="eval_runs")
    op.drop_index("ix_eval_runs_set_id", table_name="eval_runs")
    op.drop_table("eval_runs")
    op.drop_index("ix_eval_pairs_set_id", table_name="eval_pairs")
    op.drop_table("eval_pairs")
    op.drop_index("ix_eval_sets_project_id", table_name="eval_sets")
    op.drop_table("eval_sets")
