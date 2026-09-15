"""Access — the single function that decides which projects a caller may see, and the
single function that decides what they may do to one.

`docs/PRD.md` §2 and §5.1 require this to live in exactly one place, and phase 2.1's
per-project RBAC was exactly that: a change to `resolve_project_scope`'s body, plus
`require_permission` beside it, and nothing at the 15 call sites. A route, service, or
query that filters projects on its own is a defect even when its output is currently
identical (`.claude/rules/router.md`), and `tests/test_scoping_is_single_point.py`
enforces that as a grep.

Returns an explicit `ProjectScope` rather than `list[UUID] | None`. A `None` sentinel
meaning "unrestricted" is fail-open: any accidental `None` anywhere would read as full
access. This way a caller has to branch on `unrestricted` deliberately, and an empty
`ids` set means no access rather than all of it.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Self

from fastapi import status

from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.core.permissions import Permission


@dataclass(frozen=True, slots=True)
class ProjectScope:
    """Which projects a caller may read.

    Exactly one of the two states is meaningful: `unrestricted` (every project on the
    instance) or a concrete `ids` set. An unrestricted scope carries no ids, so there
    is never a second source of truth to disagree.
    """

    unrestricted: bool
    ids: frozenset[uuid.UUID] = field(default_factory=frozenset)

    @classmethod
    def all(cls) -> Self:
        """Every project on the instance. An administrator's answer."""
        return cls(unrestricted=True, ids=frozenset())

    @classmethod
    def of(cls, ids: Iterable[uuid.UUID]) -> Self:
        """Exactly these projects. An empty set means none — not all."""
        return cls(unrestricted=False, ids=frozenset(ids))


def resolve_project_scope(user: AuthenticatedUser) -> ProjectScope:
    """Which projects this caller may read.

    Phase 2.1: the projects they hold a membership on, or every project for an
    administrator. The grants are loaded once per request by `AuthContextMiddleware`,
    which is what keeps this function synchronous and its call sites untouched.

    An empty `ids` set means **no access**. It is never `unrestricted` by accident:
    that state has to be constructed deliberately with `ProjectScope.all()`.
    """
    if user.is_admin:
        return ProjectScope.all()
    return ProjectScope.of(grant.project_id for grant in user.grants.values())


def require_permission(
    user: AuthenticatedUser, project_id: uuid.UUID, permission: Permission
) -> None:
    """Raise unless this caller may perform `permission` on this project.

    The `403`/`404` split is a security decision, not a formatting one
    (`.claude/rules/response-api.md`):

    - **No membership → `404`.** Once projects are not shared, "you may not see this"
      and "this does not exist" are the same answer. A `403` would confirm a private
      repository exists to anyone who can guess an id.
    - **A member whose role is too low → `403`.** They can already see the project in
      their own list, so `404` would contradict what the UI just rendered.

    An administrator passes every check. That is safe because the catalogue contains
    no `conversation.*` permission — there is nothing here to bypass into, and
    `tests/test_permissions.py` fails if one is ever added.

    Synchronous on purpose: the grants are already in hand, so this does no I/O and
    can be called from anywhere a service already holds the caller.
    """
    if user.is_admin:
        return

    grant = user.grants.get(project_id)
    if grant is None:
        raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found.")
    if permission.value not in grant.permissions:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.INSUFFICIENT_ROLE,
            f"Your role on this project ({grant.role}) does not allow that.",
        )


def permissions_for(user: AuthenticatedUser, project_id: uuid.UUID) -> frozenset[str]:
    """This caller's effective permissions on one project.

    Serialized onto `ProjectResponse` so the frontend can hide controls it would be
    refused. Hiding is cosmetic — `require_permission` is the control.
    """
    if user.is_admin:
        return frozenset(p.value for p in Permission)
    grant = user.grants.get(project_id)
    return grant.permissions if grant else frozenset()


def role_for(user: AuthenticatedUser, project_id: uuid.UUID) -> str | None:
    """This caller's role name on one project, or `None`.

    `None` for an administrator with no membership: they have every permission but no
    role, and inventing one would put a word on screen that matches no row.
    """
    grant = user.grants.get(project_id)
    return grant.role if grant else None


def resolve_conversation_owner(user: AuthenticatedUser) -> uuid.UUID:
    """Whose conversations this caller may read. Phase 1: only their own.

    The counterpart to `resolve_project_scope`, and deliberately in the same file so
    the contrast is visible rather than folklore: projects are shared instance-wide,
    conversations are private to one user.

    `is_admin` is **not** consulted. It gates destructive operations on *shared*
    resources; conversations are not shared, and `docs/PRD.md` §4.2 states their
    privacy to users without qualification. An administrator who could read a
    colleague's conversation would make that statement false.

    `docs/PRD.md` §4.2 lists sharing a conversation as out of scope *for v1*, which
    marks it as a change someone will eventually make. This is the one body they
    change.
    """
    return user.id
