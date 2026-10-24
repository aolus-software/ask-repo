"""add eval languages

Revision ID: e7c2b9d41f06
Revises: c4e8a1f20b97
"""

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects.postgresql import UUID as PgUUID

from alembic import op

revision: str = "e7c2b9d41f06"
down_revision: str | Sequence[str] | None = "c4e8a1f20b97"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_sets",
        sa.Column("language", sa.String(length=8), nullable=False, server_default=sa.text("'en'")),
    )
    op.add_column("eval_sets", sa.Column("source_set_id", PgUUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_eval_sets_source_set_id_eval_sets", "eval_sets", "eval_sets", ["source_set_id"], ["id"]
    )
    op.create_index(
        "uq_eval_sets_source_language",
        "eval_sets",
        ["source_set_id", "language"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL AND source_set_id IS NOT NULL"),
    )
    op.add_column("eval_pairs", sa.Column("source_pair_id", PgUUID(as_uuid=True), nullable=True))
    op.create_foreign_key(
        "fk_eval_pairs_source_pair_id_eval_pairs",
        "eval_pairs",
        "eval_pairs",
        ["source_pair_id"],
        ["id"],
    )
    op.add_column("eval_pairs", sa.Column("exclusion_reason", sa.String(length=32), nullable=True))


def downgrade() -> None:
    op.drop_column("eval_pairs", "exclusion_reason")
    op.drop_constraint("fk_eval_pairs_source_pair_id_eval_pairs", "eval_pairs", type_="foreignkey")
    op.drop_column("eval_pairs", "source_pair_id")
    op.drop_index("uq_eval_sets_source_language", table_name="eval_sets")
    op.drop_constraint("fk_eval_sets_source_set_id_eval_sets", "eval_sets", type_="foreignkey")
    op.drop_column("eval_sets", "source_set_id")
    op.drop_column("eval_sets", "language")
