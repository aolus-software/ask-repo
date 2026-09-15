"""Granting, changing and revoking project membership.

Every method gates through `access.require_permission`, so the `403`/`404` split is
the same one every other project-scoped route gets — a non-member cannot learn a
project exists by asking who its members are.

The last-owner guard lives here rather than in the route because two operations can
strand a project: revoking an owner, and demoting one. A route-level check would have
to be written twice.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.grant_cache import get_grant_cache
from app.core.middleware import AuthenticatedUser
from app.core.permissions import OWNER_NAME, Permission
from app.models.membership import ProjectMembership
from app.repositories.membership import MembershipRepository
from app.repositories.role import RoleRepository
from app.repositories.user import UserRepository
from app.schemas.membership import MemberCreateRequest, MemberResponse, MemberUpdateRequest


class MembershipService:
    """Project membership. One service call per route."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self._members = MembershipRepository(session)
        self._roles = RoleRepository(session)
        self._users = UserRepository(session)

    async def list_members(
        self, project_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> Sequence[MemberResponse]:
        """Who can reach this project. Requires `membership.read`, which every role
        holds — so any member sees who else has access."""
        access.require_permission(actor, project_id, Permission.MEMBERSHIP_READ)

        rows = await self._members.list_for_project(project_id)
        responses = []
        for row in rows:
            user = await self._users.get(row.user_id)
            role = await self._roles.get(row.role_id)
            if user is None or role is None:
                continue
            responses.append(
                MemberResponse(
                    user_id=user.id,
                    name=user.name,
                    email=user.email,
                    role=role.name,
                    granted_by=row.granted_by,
                    granted_at=row.created_at,
                )
            )
        return responses

    async def grant(
        self, project_id: uuid.UUID, payload: MemberCreateRequest, *, actor: AuthenticatedUser
    ) -> MemberResponse:
        """Give a user a role on this project."""
        access.require_permission(actor, project_id, Permission.MEMBERSHIP_GRANT)

        role = await self._roles.get_by_name(payload.role)
        if role is None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.ROLE_NOT_FOUND, "Role not found.")
        user = await self._users.get(payload.user_id)
        if user is None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.USER_NOT_FOUND, "User not found.")
        if await self._members.get_for(payload.user_id, project_id) is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.MEMBERSHIP_EXISTS,
                "That user already has a role on this project.",
            )

        membership = ProjectMembership(
            id=uuid.uuid4(),
            user_id=user.id,
            project_id=project_id,
            role_id=role.id,
            granted_by=actor.id,
        )
        self.session.add(membership)
        await self.session.commit()
        await get_grant_cache().invalidate_user(user.id)

        return MemberResponse(
            user_id=user.id,
            name=user.name,
            email=user.email,
            role=role.name,
            granted_by=actor.id,
            granted_at=membership.created_at,
        )

    async def change_role(
        self,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        payload: MemberUpdateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> MemberResponse:
        """Swap a member's role. Refuses if it would strand the project."""
        access.require_permission(actor, project_id, Permission.MEMBERSHIP_GRANT)

        membership = await self._members.get_for(user_id, project_id)
        if membership is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.MEMBERSHIP_NOT_FOUND,
                "That user has no role on this project.",
            )
        role = await self._roles.get_by_name(payload.role)
        if role is None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.ROLE_NOT_FOUND, "Role not found.")
        if role.name != OWNER_NAME:
            await self._refuse_if_last_owner(project_id, user_id)

        membership.role_id = role.id
        await self.session.commit()
        await get_grant_cache().invalidate_user(user_id)

        user = await self._users.get(user_id)
        assert user is not None  # type: ignore[assert-type]
        return MemberResponse(
            user_id=user.id,
            name=user.name,
            email=user.email,
            role=role.name,
            granted_by=membership.granted_by,
            granted_at=membership.created_at,
        )

    async def revoke(
        self, project_id: uuid.UUID, user_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> None:
        """Remove someone's access. Refuses if it would strand the project."""
        access.require_permission(actor, project_id, Permission.MEMBERSHIP_REVOKE)

        membership = await self._members.get_for(user_id, project_id)
        if membership is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.MEMBERSHIP_NOT_FOUND,
                "That user has no role on this project.",
            )
        await self._refuse_if_last_owner(project_id, user_id)

        membership.deleted_at = datetime.now(UTC)
        await self.session.commit()
        await get_grant_cache().invalidate_user(user_id)

    async def _refuse_if_last_owner(self, project_id: uuid.UUID, user_id: uuid.UUID) -> None:
        """Every live project keeps at least one live owner.

        Both revoking and demoting can break it, which is why the check is here and
        not written twice at the routes.
        """
        if await self._members.count_live_owners(project_id, excluding_user=user_id) == 0:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.LAST_OWNER,
                "This project would be left with no owner. Give someone else the owner role first.",
            )
