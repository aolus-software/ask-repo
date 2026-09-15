"""add rbac tables

Creates roles, role_permissions and project_memberships, seeds the three system
roles, and backfills one owner membership per live project from `created_by`.

The backfill deliberately does not fabricate owners for deactivated creators. It
seeds `created_by` unconditionally, preserving attribution; where that account is
already soft-deleted the project starts with no *live* owner. Admins bypass every
project permission, so those projects stay operable, and `GET /projects?ownerless=true`
lists them. The `409 LAST_OWNER` guard prevents new strandings; it cannot rewrite
history, and auto-granting an arbitrary admin would write a grant nobody made.

Revision ID: 58f7e042f75a
Revises: f1115e97d693
Create Date: 2026-09-13 21:44:28.917303
"""

import uuid
from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op
from app.core.permissions import SYSTEM_ROLE_DESCRIPTIONS, SYSTEM_ROLES

revision: str = "58f7e042f75a"
down_revision: str | None = "f1115e97d693"
branch_labels: Sequence[str] | None = None
depends_on: Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "roles",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("name", sa.String(length=64), nullable=False),
        sa.Column("description", sa.String(length=255), nullable=True),
        sa.Column("is_system", sa.Boolean(), server_default=sa.text("false"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_roles")),
    )
    op.create_index(
        "uq_roles_name",
        "roles",
        ["name"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "role_permissions",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("permission", sa.String(length=64), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_role_permissions_role_id_roles")
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_role_permissions")),
    )
    op.create_index(
        "uq_role_permissions_role_id",
        "role_permissions",
        ["role_id", "permission"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    op.create_table(
        "project_memberships",
        sa.Column("id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("user_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("project_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("role_id", sa.UUID(as_uuid=True), nullable=False),
        sa.Column("granted_by", sa.UUID(as_uuid=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.Column("deleted_at", sa.DateTime(timezone=True), nullable=True),
        sa.ForeignKeyConstraint(
            ["user_id"], ["users.id"], name=op.f("fk_project_memberships_user_id_users")
        ),
        sa.ForeignKeyConstraint(
            ["project_id"],
            ["projects.id"],
            name=op.f("fk_project_memberships_project_id_projects"),
        ),
        sa.ForeignKeyConstraint(
            ["role_id"], ["roles.id"], name=op.f("fk_project_memberships_role_id_roles")
        ),
        sa.ForeignKeyConstraint(
            ["granted_by"],
            ["users.id"],
            name=op.f("fk_project_memberships_granted_by_users"),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_project_memberships")),
    )
    op.create_index(
        "uq_project_memberships_user_id",
        "project_memberships",
        ["user_id", "project_id"],
        unique=True,
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_project_memberships_user_id",
        "project_memberships",
        ["user_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )
    op.create_index(
        "ix_project_memberships_project_id",
        "project_memberships",
        ["project_id"],
        postgresql_where=sa.text("deleted_at IS NULL"),
    )

    _seed_system_roles()
    _backfill_owner_memberships()


def _seed_system_roles() -> None:
    """Insert viewer / editor / owner with their permission sets."""
    connection = op.get_bind()
    for name, permissions in SYSTEM_ROLES.items():
        role_id = uuid.uuid4()
        connection.execute(
            sa.text(
                "INSERT INTO roles (id, name, description, is_system) "
                "VALUES (:id, :name, :description, true)"
            ),
            {"id": role_id, "name": name, "description": SYSTEM_ROLE_DESCRIPTIONS[name]},
        )
        connection.execute(
            sa.text(
                "INSERT INTO role_permissions (id, role_id, permission) "
                "VALUES (:id, :role_id, :permission)"
            ),
            [
                {"id": uuid.uuid4(), "role_id": role_id, "permission": p.value}
                for p in sorted(permissions)
            ],
        )


def _backfill_owner_memberships() -> None:
    """One owner membership per live project, from `created_by`.

    `created_at` is copied from the project so the row is not retroactively dated
    today. Soft-deleted projects are skipped: they are unreachable already, and
    seeding them would resurrect membership for something nobody can list.
    """
    op.get_bind().execute(
        sa.text(
            """
            INSERT INTO project_memberships
                (id, user_id, project_id, role_id, granted_by, created_at, updated_at)
            SELECT gen_random_uuid(),
                   p.created_by,
                   p.id,
                   (SELECT id FROM roles WHERE name = 'owner' AND deleted_at IS NULL),
                   NULL,
                   p.created_at,
                   p.created_at
            FROM projects p
            WHERE p.deleted_at IS NULL
            """
        )
    )


def downgrade() -> None:
    op.drop_table("project_memberships")
    op.drop_table("role_permissions")
    op.drop_table("roles")
