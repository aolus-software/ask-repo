"""Read scoping — the single function that decides which projects a caller may see.

`docs/PRD.md` §2 and §5.1 require this to live in exactly one place, so phase 2's
per-project RBAC is a change to `resolve_project_scope`'s body and nothing else. A
route, service, or query that filters projects on its own is a defect even when its
output is currently identical (`.claude/rules/router.md`).

Returns an explicit `ProjectScope` rather than `list[UUID] | None`. A `None` sentinel
meaning "unrestricted" is fail-open: any accidental `None` anywhere would read as full
access. This way a caller has to branch on `unrestricted` deliberately, and an empty
`ids` set means no access rather than all of it.
"""

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from typing import Self

from app.core.middleware import AuthenticatedUser


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
        """Every project on the instance. Phase 1's answer for everyone."""
        return cls(unrestricted=True, ids=frozenset())

    @classmethod
    def of(cls, ids: Iterable[uuid.UUID]) -> Self:
        """Exactly these projects. An empty set means none — not all."""
        return cls(unrestricted=False, ids=frozenset(ids))


def resolve_project_scope(user: AuthenticatedUser) -> ProjectScope:
    """Which projects this caller may read.

    Phase 1: every project on the instance, for every authenticated user. That is
    intended behaviour, not an oversight — `docs/PRD.md` §4.1 and `SECURITY.md:34` both
    say so, and `is_admin` gates destructive operations rather than reads.

    Phase 2 replaces this body with a membership lookup. Nothing that calls it changes.
    """
    return ProjectScope.all()


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
