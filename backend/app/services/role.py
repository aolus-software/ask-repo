"""Role definitions: list, create, re-permission, delete.

System roles are frozen. That is what makes this table safe to expose in an admin
UI — without it, one unchecked box on `owner` leaves the instance unable to grant
membership, recoverable only by SQL or the CLI.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.audit import AuditEntry, AuditEventType, AuditRecorder, ChangedValue
from app.core.errors import AppError, ErrorCode
from app.core.grant_cache import get_grant_cache
from app.core.middleware import AuthenticatedUser
from app.core.permissions import PERMISSION_GROUPS
from app.models.membership import Role
from app.repositories.role import RoleRepository
from app.schemas.role import (
    PermissionCatalogResponse,
    PermissionGroupResponse,
    RoleCreateRequest,
    RoleResponse,
    RoleUpdateRequest,
)


class RoleService:
    """Role CRUD. Admin-only at the route; no project scoping applies — roles are
    instance-wide definitions, not project-scoped resources."""

    def __init__(self, session: AsyncSession, *, recorder: AuditRecorder) -> None:
        self.session = session
        self._roles = RoleRepository(session)
        self._recorder = recorder

    @staticmethod
    def catalogue() -> PermissionCatalogResponse:
        """Every permission, grouped and labelled.

        Labels come from the server because the catalogue is the server's enum;
        deriving them client-side by splitting on `.` would need a second copy of the
        human-readable names.
        """
        return PermissionCatalogResponse(
            groups=[
                PermissionGroupResponse(
                    label=group.label, permissions=[p.value for p in group.permissions]
                )
                for group in PERMISSION_GROUPS
            ]
        )

    async def list_roles(self) -> Sequence[RoleResponse]:
        """Every live role, system first."""
        return [await self._to_response(role) for role in await self._roles.list_all()]

    async def create(self, payload: RoleCreateRequest, *, actor: AuthenticatedUser) -> RoleResponse:
        """A custom role, with no permissions yet — the matrix page sets those."""
        if await self._roles.get_by_name(payload.name) is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ROLE_NAME_EXISTS,
                "A role with that name already exists.",
            )
        role = Role(
            id=uuid.uuid4(),
            name=payload.name,
            description=payload.description,
            is_system=False,
        )
        self.session.add(role)
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.ROLE_CREATED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="role",
                target_id=role.id,
                target_label=role.name,
                changed={
                    "name": (None, role.name),
                    "description": (None, role.description),
                    "permissions": (None, []),
                },
            )
        )
        return await self._to_response(role)

    async def update(
        self, role_id: uuid.UUID, payload: RoleUpdateRequest, *, actor: AuthenticatedUser
    ) -> RoleResponse:
        """Rename a custom role and/or replace its permission set."""
        role = await self._require_editable(role_id)

        old_name = role.name
        old_description = role.description
        # Captured before `replace_permissions` writes the new rows: that call
        # replaces `role_permissions` for this role, so reading afterwards would
        # yield the new set for both sides of the diff and silently turn it into a
        # no-op.
        old_permissions = sorted(await self._roles.permissions_for(role.id))

        if payload.name is not None and payload.name != role.name:
            existing = await self._roles.get_by_name(payload.name)
            if existing is not None:
                raise AppError(
                    status.HTTP_409_CONFLICT,
                    ErrorCode.ROLE_NAME_EXISTS,
                    "A role with that name already exists.",
                )
            role.name = payload.name
        if payload.description is not None:
            role.description = payload.description
        if payload.permissions is not None:
            await self._roles.replace_permissions(role.id, payload.permissions)

        await self.session.commit()
        await get_grant_cache().bump_epoch()

        changed: dict[str, tuple[ChangedValue, ChangedValue]] = {}
        if role.name != old_name:
            changed["name"] = (old_name, role.name)
        if role.description != old_description:
            changed["description"] = (old_description, role.description)
        new_permissions = sorted(await self._roles.permissions_for(role.id))
        if new_permissions != old_permissions:
            changed["permissions"] = (old_permissions, new_permissions)
        if changed:
            await self._recorder.record(
                AuditEntry(
                    event_type=AuditEventType.ROLE_UPDATED,
                    actor_user_id=actor.id,
                    actor_email=actor.email,
                    target_type="role",
                    target_id=role.id,
                    target_label=role.name,
                    changed=changed,
                )
            )
        return await self._to_response(role)

    async def delete(self, role_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete a custom role that nobody holds."""
        role = await self._require_editable(role_id)

        if await self._roles.member_count(role.id) > 0:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ROLE_IN_USE,
                "That role is still assigned on at least one project. Change those "
                "memberships first.",
            )
        permissions = sorted(await self._roles.permissions_for(role.id))
        role_name = role.name
        role.deleted_at = datetime.now(UTC)
        await self.session.commit()
        await get_grant_cache().bump_epoch()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.ROLE_DELETED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="role",
                target_id=role.id,
                target_label=role_name,
                changed={
                    "name": (role_name, None),
                    "permissions": (permissions, None),
                },
            )
        )

    async def _require_editable(self, role_id: uuid.UUID) -> Role:
        """Load a role, refusing if it is a system role."""
        role = await self._roles.get(role_id)
        if role is None or role.deleted_at is not None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.ROLE_NOT_FOUND, "Role not found.")
        if role.is_system:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                ErrorCode.SYSTEM_ROLE_IMMUTABLE,
                "viewer, editor and owner are built in and cannot be changed.",
            )
        return role

    async def _to_response(self, role: Role) -> RoleResponse:
        return RoleResponse(
            id=role.id,
            name=role.name,
            description=role.description,
            is_system=role.is_system,
            permissions=sorted(await self._roles.permissions_for(role.id)),
            member_count=await self._roles.member_count(role.id),
        )
