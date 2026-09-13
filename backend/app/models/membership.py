"""Per-project RBAC: roles, their permissions, and who holds them where.

Roles are **instance-wide definitions**; the assignment carries the project. That
separation is what lets one "QA Lead" role be granted on twelve projects without
twelve role rows.

Every unique index here is **partial** on `deleted_at IS NULL`. Soft delete means a
revoked membership stays as a row, and without the `WHERE` clause re-granting access
to someone previously revoked collides on a row nobody can see — with an error naming
a constraint the admin cannot observe.
"""

import uuid

from sqlalchemy import Boolean, ForeignKey, Index, String, text
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class Role(Base, TimestampMixin, SoftDeleteMixin):
    """A named bundle of permissions.

    `is_system` marks viewer/editor/owner, which cannot be renamed, deleted, or
    re-permissioned. That immutability is what makes the role table safe to expose:
    without it, unchecking `membership.grant` on `owner` leaves nobody on the instance
    able to grant membership, including to undo it.
    """

    __tablename__ = "roles"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    name: Mapped[str] = mapped_column(String(64), nullable=False)
    description: Mapped[str | None] = mapped_column(String(255), nullable=True)
    is_system: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default=text("false"))

    __table_args__ = (
        Index(
            "uq_roles_name",
            "name",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class RolePermission(Base, TimestampMixin, SoftDeleteMixin):
    """One permission held by one role.

    `permission` is a validated string, **not** a foreign key to a `permissions`
    table. Existence is anchored in `app.core.permissions.Permission` — see that
    module's docstring for why a table would be a footgun.
    """

    __tablename__ = "role_permissions"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    permission: Mapped[str] = mapped_column(String(64), nullable=False)

    __table_args__ = (
        Index(
            "uq_role_permissions_role_id",
            "role_id",
            "permission",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )


class ProjectMembership(Base, TimestampMixin, SoftDeleteMixin):
    """Who may reach a project, and as what.

    Spatie's `model_has_roles` with its team scope, minus the polymorphism: only users
    hold roles here, so a `model_type` column would be the constant 'users' in every
    row.

    One role per user per project (the partial unique below). Multiple simultaneous
    roles would make the effective permission set a union that no single row explains.
    """

    __tablename__ = "project_memberships"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    role_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("roles.id"), nullable=False
    )
    # NULL for rows the backfill derived from `created_by`: nobody granted those.
    # Phase 2.2's audit trail reads this column first, and a fabricated granter would
    # be a lie recorded as fact in the one table whose purpose is being trustworthy.
    granted_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )

    __table_args__ = (
        Index(
            "uq_project_memberships_user_id",
            "user_id",
            "project_id",
            unique=True,
            postgresql_where=text("deleted_at IS NULL"),
        ),
        # The middleware's hot path: read on every authenticated request.
        Index(
            "ix_project_memberships_user_id",
            "user_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
        Index(
            "ix_project_memberships_project_id",
            "project_id",
            postgresql_where=text("deleted_at IS NULL"),
        ),
    )
