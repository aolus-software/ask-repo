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
from app.core.middleware import AuthenticatedUser, ProjectGrant
from app.core.permissions import Permission
from app.repositories.membership import MembershipRepository


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

    def narrowed_to(self, ids: Iterable[uuid.UUID]) -> Self:
        """This scope restricted to `ids` — never widened past what it already allows.

        A filter (`?ownerless=true`) selects projects on a property that has nothing to
        do with access, so it has to be applied *on top of* the resolver's answer rather
        than in place of it. Replacing the scope would make the filter a second
        enforcement point, which `docs/PRD.md` §7 exists to prevent.

        The unrestricted case is why this is a method and not a set intersection at the
        call site: an unrestricted scope carries no ids, so intersecting with its empty
        `ids` would return nothing instead of everything.
        """
        requested = frozenset(ids)
        if self.unrestricted:
            return type(self)(unrestricted=False, ids=requested)
        return type(self)(unrestricted=False, ids=self.ids & requested)


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


def memberships_for(user: AuthenticatedUser) -> list[ProjectGrant]:
    """The projects this caller actually holds a membership on, with the role on each.

    A different question from `resolve_project_scope`: that one answers "what may I
    read", and an administrator may read everything. This answers "where am I a
    member", and an administrator is a member only where someone granted it. Read from
    the snapshot the middleware already loaded — no I/O, and the only membership read
    the profile makes (`tests/test_scoping_is_single_point.py`).
    """
    return list(user.grants.values())


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


async def resolve_notification_recipients(
    memberships: MembershipRepository,
    project_id: uuid.UUID,
    permission: Permission,
    *,
    excluding: uuid.UUID | None,
) -> frozenset[uuid.UUID]:
    """Who hears about an event on this project.

    `resolve_project_scope` answers "which projects may this caller read"; this
    answers the same question from the other end — "which callers may read this
    project, and hold the permission this event is about". `docs/PRD.md` §2.1 requires
    it to resolve through membership rather than through a recipient list this feature
    invents, and names the failure it is guarding: not an empty list, but a
    notification naming a private repository to someone who was never given it.

    **This is the file's first async function, and that is a real divergence rather
    than an oversight.** The others are synchronous because the grants are already in
    hand — `AuthContextMiddleware` loaded them for this request's user. There is no
    equivalent here: the caller is frequently a worker with no request and no
    `AuthenticatedUser`, asking about users it has never seen.

    **An administrator with no membership is not a recipient.** `require_permission`
    lets an admin pass every check, and mirroring that here would notify every admin
    about every project on the instance. Permission to see a thing is not interest in
    hearing about it; adding an `is_admin` branch for symmetry is the bug.

    It takes the repository rather than a session so this module stays free of query
    construction, exactly as it is today.
    """
    recipients = frozenset(await memberships.recipients_for(project_id, permission))
    if excluding is None:
        return recipients
    return recipients - {excluding}


def resolve_notification_owner(user: AuthenticatedUser) -> uuid.UUID:
    """Whose notifications this caller may read: only their own.

    Beside `resolve_conversation_owner` for the same reason it is beside
    `resolve_project_scope` — so "whose rows are these" is decided in one file rather
    than by a `user_id ==` filter in a service. `is_admin` is not consulted: there is
    no administrative view of anyone's notifications, and nothing needs one, because
    the underlying *actions* are already visible to an administrator through
    `/audit-events` wherever they were audited.

    This is the one body someone changes if notifications ever become shareable.
    """
    return user.id
