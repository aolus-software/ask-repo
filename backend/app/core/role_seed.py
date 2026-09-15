"""Install the three system roles, idempotently.

The RBAC migration seeds viewer/editor/owner as part of `upgrade()`. This module is
the *runtime* equivalent: it brings an existing database back to that state without a
migration, which is what the test harness needs after it truncates every table and
what `restore-system-roles` will offer an operator whose seed was damaged.

**The migration deliberately keeps its own raw SQL rather than calling this.** A
migration must be self-contained: importing application ORM code means a later model
change silently alters what an old revision does when it is replayed on a fresh
database. What the two share is the *data* -- `SYSTEM_ROLES` and
`SYSTEM_ROLE_DESCRIPTIONS` -- so they cannot disagree about which permissions a system
role carries. Two mechanisms, one source of truth; do not "fix" the duplication by
having the migration import this function.

This lives here rather than in `app.core.permissions` because that module is
deliberately pure: no session, no I/O, nothing to mock.
"""

from datetime import UTC, datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.permissions import SYSTEM_ROLE_DESCRIPTIONS, SYSTEM_ROLES
from app.models.membership import Role, RolePermission


async def ensure_system_roles(session: AsyncSession) -> None:
    """Create or repair viewer/editor/owner so they match the catalogue exactly.

    Safe on an empty database and on a populated one: a missing role is created, an
    existing one has `is_system`, `description` and its permission set reconciled
    against `SYSTEM_ROLES`. Custom roles are never touched. The caller commits.
    """
    for name, permissions in SYSTEM_ROLES.items():
        role = (
            await session.execute(select(Role).where(Role.name == name, Role.deleted_at.is_(None)))
        ).scalar_one_or_none()

        if role is None:
            role = Role(name=name, description=SYSTEM_ROLE_DESCRIPTIONS[name], is_system=True)
            session.add(role)
            await session.flush()
        else:
            role.description = SYSTEM_ROLE_DESCRIPTIONS[name]
            role.is_system = True

        await _reconcile_permissions(session, role, {p.value for p in permissions})

    await session.flush()


async def _reconcile_permissions(session: AsyncSession, role: Role, wanted: set[str]) -> None:
    """Add the permissions the role is missing and soft-delete the ones it should not hold."""
    existing = (
        (
            await session.execute(
                select(RolePermission).where(
                    RolePermission.role_id == role.id,
                    RolePermission.deleted_at.is_(None),
                )
            )
        )
        .scalars()
        .all()
    )

    held = {row.permission for row in existing}
    for row in existing:
        if row.permission not in wanted:
            row.deleted_at = datetime.now(UTC)

    for permission in sorted(wanted - held):
        session.add(RolePermission(role_id=role.id, permission=permission))
