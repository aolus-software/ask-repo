"""grant eval permissions to the system roles

Self-contained on purpose: literals only, nothing imported from `app`, so a later change
to the catalogue cannot alter what this revision does when replayed
(see `app/core/role_seed.py`).

Revision ID: c5f2a7d81e36
Revises: b3e81f4c2a90
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "c5f2a7d81e36"
down_revision: str | Sequence[str] | None = "b3e81f4c2a90"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

GRANTS = {
    "viewer": ("eval.read",),
    "editor": ("eval.read", "eval.run"),
    "owner": ("eval.read", "eval.run"),
}


def upgrade() -> None:
    connection = op.get_bind()
    for role, permissions in GRANTS.items():
        role_id = connection.execute(
            sa.text("SELECT id FROM roles WHERE name = :name AND is_system AND deleted_at IS NULL"),
            {"name": role},
        ).scalar_one_or_none()
        if role_id is None:
            continue
        for permission in permissions:
            connection.execute(
                sa.text(
                    "INSERT INTO role_permissions (id, role_id, permission) "
                    "SELECT :id, :role_id, CAST(:permission AS varchar) WHERE NOT EXISTS ("
                    "SELECT 1 FROM role_permissions WHERE role_id = :role_id "
                    "AND permission = CAST(:permission AS varchar) AND deleted_at IS NULL)"
                ),
                {"id": uuid.uuid4(), "role_id": role_id, "permission": permission},
            )


def downgrade() -> None:
    op.execute("DELETE FROM role_permissions WHERE permission IN ('eval.read', 'eval.run')")
