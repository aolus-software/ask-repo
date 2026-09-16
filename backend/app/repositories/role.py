"""Queries over `roles` and `role_permissions`.

Unscoped by `ProjectScope`: roles are instance-wide definitions, and which *projects*
a caller may see has no bearing on which roles exist. Who may read this table is an
admin question, answered at the route.
"""

import uuid
from collections.abc import Iterable, Sequence
from datetime import UTC, datetime

from sqlalchemy import func, select, update

from app.models.membership import ProjectMembership, Role, RolePermission
from app.repositories.base import BaseRepository


class RoleRepository(BaseRepository[Role]):
    """Reads and writes for role definitions. All reads exclude soft-deleted rows."""

    model = Role

    async def get_by_name(self, name: str) -> Role | None:
        """Find a live role by name. Names are unique among live rows."""
        result = await self.session.execute(self.active_select().where(Role.name == name))
        return result.scalar_one_or_none()

    async def list_all(self) -> Sequence[Role]:
        """Every live role, system roles first, then alphabetical."""
        result = await self.session.execute(
            self.active_select().order_by(Role.is_system.desc(), Role.name.asc())
        )
        return result.scalars().all()

    async def permissions_for(self, role_id: uuid.UUID) -> frozenset[str]:
        """The permission strings this role holds."""
        result = await self.session.execute(
            select(RolePermission.permission).where(
                RolePermission.role_id == role_id,
                RolePermission.deleted_at.is_(None),
            )
        )
        return frozenset(result.scalars().all())

    async def replace_permissions(self, role_id: uuid.UUID, permissions: Iterable[str]) -> None:
        """Soft-delete the current set and insert the new one.

        Soft delete rather than DELETE so the change is visible to Phase 2.2's audit
        trail. `updated_at` is set explicitly: this is a bulk Core `UPDATE`, which does
        not go through the ORM path that `onupdate` fires on
        (`.claude/rules/persistence.md`).
        """
        now = datetime.now(UTC)
        await self.session.execute(
            update(RolePermission)
            .where(RolePermission.role_id == role_id, RolePermission.deleted_at.is_(None))
            .values(deleted_at=now, updated_at=now)
        )
        for permission in sorted(set(permissions)):
            self.session.add(
                RolePermission(id=uuid.uuid4(), role_id=role_id, permission=permission)
            )

    async def member_count(self, role_id: uuid.UUID) -> int:
        """How many live memberships reference this role.

        Answers `409 ROLE_IN_USE` before an admin attempts the delete, and populates
        the Members column on the role list.
        """
        result = await self.session.execute(
            select(func.count())
            .select_from(ProjectMembership)
            .where(
                ProjectMembership.role_id == role_id,
                ProjectMembership.deleted_at.is_(None),
            )
        )
        return result.scalar_one()
