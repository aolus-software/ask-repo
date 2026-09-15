"""Queries over `project_memberships`.

`load_grants` is on the hot path — it runs on every authenticated request via
`AuthContextMiddleware` — so it is one query with two joins, never a per-project
lookup. `ix_project_memberships_user_id` is the index it depends on.

Unscoped by `ProjectScope`, deliberately: this repository is what *produces* the
scope. Scoping it by the scope would be circular.
"""

import uuid
from collections.abc import Sequence

from sqlalchemy import func, select

from app.core.permissions import OWNER_NAME
from app.models.membership import ProjectMembership, Role, RolePermission
from app.models.project import Project
from app.models.user import User
from app.repositories.base import BaseRepository


class MembershipRepository(BaseRepository[ProjectMembership]):
    """Reads and writes for project membership."""

    model = ProjectMembership

    async def load_grants(self, user_id: uuid.UUID) -> dict[uuid.UUID, tuple[str, frozenset[str]]]:
        """Every project this user may reach, with the role name and expanded set.

        Returns `{project_id: (role_name, permissions)}`. An empty dict means no
        access — never "all", which is the failure `ProjectScope`'s two-state design
        exists to make unrepresentable.

        The permission join is an `outerjoin` with the soft-delete condition in the
        `ON` clause rather than the `WHERE`: a role whose permissions have all been
        revoked still has to appear, because holding a role with nothing attached is
        access to the project and no more. Moving that condition to the `WHERE` would
        silently drop the whole membership instead.
        """
        result = await self.session.execute(
            select(ProjectMembership.project_id, Role.name, RolePermission.permission)
            .join(Role, Role.id == ProjectMembership.role_id)
            .outerjoin(
                RolePermission,
                (RolePermission.role_id == Role.id) & RolePermission.deleted_at.is_(None),
            )
            .where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.deleted_at.is_(None),
                Role.deleted_at.is_(None),
            )
        )

        collected: dict[uuid.UUID, tuple[str, set[str]]] = {}
        for project_id, role_name, permission in result.all():
            _, permissions = collected.setdefault(project_id, (role_name, set()))
            if permission is not None:
                permissions.add(permission)
        return {
            project_id: (role_name, frozenset(permissions))
            for project_id, (role_name, permissions) in collected.items()
        }

    async def get_for(self, user_id: uuid.UUID, project_id: uuid.UUID) -> ProjectMembership | None:
        """This user's live membership on this project, if any."""
        result = await self.session.execute(
            self.active_select().where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.project_id == project_id,
            )
        )
        return result.scalar_one_or_none()

    async def grant(
        self,
        *,
        project_id: uuid.UUID,
        user_id: uuid.UUID,
        role_id: uuid.UUID,
        granted_by: uuid.UUID,
    ) -> ProjectMembership:
        """Give a user a role on a project, without committing.

        Constructing the row lives here rather than in the calling service because a
        service that builds a `ProjectMembership` itself is a second place that
        decides who may reach a project — exactly what
        `tests/test_scoping_is_single_point.py` refuses, and what `docs/PRD.md` §7's
        single-point criterion exists to prevent.

        Flushes rather than commits, so the caller can write the project row and its
        owner membership in one transaction. A project that exists with no owner
        breaks the invariant §9 enforces, and a second transaction is a window where
        exactly that is true.
        """
        membership = ProjectMembership(
            id=uuid.uuid4(),
            user_id=user_id,
            project_id=project_id,
            role_id=role_id,
            granted_by=granted_by,
        )
        self.session.add(membership)
        await self.session.flush()
        return membership

    async def list_for_project(self, project_id: uuid.UUID) -> Sequence[ProjectMembership]:
        """Every live membership on a project, oldest grant first."""
        result = await self.session.execute(
            self.active_select()
            .where(ProjectMembership.project_id == project_id)
            .order_by(ProjectMembership.created_at.asc())
        )
        return result.scalars().all()

    async def count_live_owners(
        self, project_id: uuid.UUID, *, excluding_user: uuid.UUID | None = None
    ) -> int:
        """Owners of this project whose accounts are still active.

        Reads through to the user row on purpose. Deactivating someone leaves their
        memberships intact so reactivation restores exact access, which means an owner
        row can exist for an account that cannot log in — counting rows alone would
        report a project as owned when nobody can act on it.

        `excluding_user` answers "would this operation leave none?" — the same shape as
        `UserRepository.count_active_admins`.
        """
        statement = (
            select(func.count())
            .select_from(ProjectMembership)
            .join(Role, Role.id == ProjectMembership.role_id)
            .join(User, User.id == ProjectMembership.user_id)
            .where(
                ProjectMembership.project_id == project_id,
                ProjectMembership.deleted_at.is_(None),
                Role.name == OWNER_NAME,
                Role.deleted_at.is_(None),
                User.deleted_at.is_(None),
            )
        )
        if excluding_user is not None:
            statement = statement.where(ProjectMembership.user_id != excluding_user)
        result = await self.session.execute(statement)
        return result.scalar_one()

    async def projects_solely_owned_by(self, user_id: uuid.UUID) -> Sequence[uuid.UUID]:
        """Projects that would have no live owner if this user were deactivated.

        Drives `409 LAST_OWNER` on `DELETE /users/{id}`, and the list of blocking
        projects in its body.
        """
        owned = await self.session.execute(
            select(ProjectMembership.project_id)
            .join(Role, Role.id == ProjectMembership.role_id)
            .where(
                ProjectMembership.user_id == user_id,
                ProjectMembership.deleted_at.is_(None),
                Role.name == OWNER_NAME,
                Role.deleted_at.is_(None),
            )
        )
        at_risk: list[uuid.UUID] = []
        for (project_id,) in owned.all():
            if await self.count_live_owners(project_id, excluding_user=user_id) == 0:
                at_risk.append(project_id)
        return at_risk

    async def ownerless_project_ids(self) -> Sequence[uuid.UUID]:
        """Live projects with no live owner.

        Only reachable through the admin-only `?ownerless=true` filter. These exist
        because the backfill seeds `created_by` unconditionally, including for
        accounts that were already deactivated — fabricating a replacement owner
        would write a grant nobody made (spec §6.4).

        `NOT EXISTS` over the same join `count_live_owners` uses, rather than an outer
        join counted per project. Counting is what makes this easy to get wrong: the
        owner-role and live-user conditions have to constrain the *same* membership
        row, and an outer join to `users` that is not itself conditioned on the role
        match counts a live viewer as evidence of an owner. A project whose only owner
        is deactivated would then be reported as healthy — invisible to the one tool
        built to find it.
        """
        owner_exists = (
            select(1)
            .select_from(ProjectMembership)
            .join(Role, Role.id == ProjectMembership.role_id)
            .join(User, User.id == ProjectMembership.user_id)
            .where(
                ProjectMembership.project_id == Project.id,
                ProjectMembership.deleted_at.is_(None),
                Role.name == OWNER_NAME,
                Role.deleted_at.is_(None),
                User.deleted_at.is_(None),
            )
            .exists()
        )
        result = await self.session.execute(
            select(Project.id).where(Project.deleted_at.is_(None), ~owner_exists)
        )
        return result.scalars().all()
