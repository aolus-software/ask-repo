"""Add mock_data_records.position

Revision ID: f1115e97d693
Revises: dfdb2d2d169c
Create Date: 2026-09-06

`created_at` is `server_default=func.now()`, and Postgres's `now()` is constant for the
whole transaction that applies a change set -- so every record inserted by one apply
shared an identical timestamp and `list_for_module`'s old `created_at, id` sort
collapsed onto the random uuid tiebreak, scrambling the order the model proposed.
`position` is assigned from an operation's index within its change set at apply time,
mirroring `checklist_items.position`.
"""

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "f1115e97d693"
down_revision: str | None = "dfdb2d2d169c"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

POSITION_DEFAULT = 0


def upgrade() -> None:
    # `server_default` for the backfill, then dropped: the application supplies the
    # value on every insert, and leaving a default in the schema would let a row that
    # forgot it look deliberate.
    op.add_column(
        "mock_data_records",
        sa.Column("position", sa.Integer(), nullable=False, server_default=str(POSITION_DEFAULT)),
    )
    op.alter_column("mock_data_records", "position", server_default=None)
    # `list_for_module` now sorts on (position, created_at, id) instead of
    # (created_at, id); the index follows the new sort key exactly, the way
    # `ix_checklist_items_module_id_feature_position` follows that repository's.
    op.drop_index("ix_mock_data_records_module_id_created_at", table_name="mock_data_records")
    op.create_index(
        "ix_mock_data_records_module_id_position",
        "mock_data_records",
        ["checklist_module_id", "position"],
    )


def downgrade() -> None:
    op.drop_index("ix_mock_data_records_module_id_position", table_name="mock_data_records")
    op.create_index(
        "ix_mock_data_records_module_id_created_at",
        "mock_data_records",
        ["checklist_module_id", "created_at"],
    )
    op.drop_column("mock_data_records", "position")
