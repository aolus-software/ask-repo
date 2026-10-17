"""add eval_runs.judge_prompt_version

Prompt versions became per feature (audit §9.31). A run's verdicts depend on the
judge's prompt as well as the answer graph's, so the run records both: the existing
`prompt_version` is now the answer graph's, and this column is the judge's. Runs made
before it carry `NULL`, which reads as "not recorded", never as a version.

Revision ID: a7d3e9c41b58
Revises: c5f2a7d81e36
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "a7d3e9c41b58"
down_revision: str | Sequence[str] | None = "c5f2a7d81e36"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column(
        "eval_runs", sa.Column("judge_prompt_version", sa.String(length=12), nullable=True)
    )


def downgrade() -> None:
    op.drop_column("eval_runs", "judge_prompt_version")
