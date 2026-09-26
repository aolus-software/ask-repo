"""The one function that answers "which projects may this caller read?", and the one
that answers "what may they do to this one?".

`docs/PRD.md` §7 makes single-point read scoping a success criterion. These tests plus
`test_scoping_is_single_point.py` are what it points at.
"""

import uuid
from typing import cast

import pytest
from fastapi import HTTPException

from app.core.access import (
    ProjectScope,
    memberships_for,
    permissions_for,
    require_permission,
    resolve_conversation_owner,
    resolve_project_scope,
    role_for,
)
from app.core.middleware import AuthenticatedUser, ProjectGrant
from app.core.permissions import SYSTEM_ROLES, Permission


def _user(
    *, is_admin: bool = False, grants: dict[uuid.UUID, ProjectGrant] | None = None
) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        name="Dev",
        email="dev@example.com",
        is_admin=is_admin,
        must_change_password=False,
        grants=grants or {},
    )


def _grant(project_id: uuid.UUID, role: str) -> ProjectGrant:
    return ProjectGrant(
        project_id=project_id,
        role=role,
        permissions=frozenset(p.value for p in SYSTEM_ROLES[role]),
    )


# ── resolve_project_scope ────────────────────────────────────────────────


def test_a_user_with_no_membership_sees_nothing() -> None:
    """Not 'everything'. An empty `ids` set means no access, which is the whole
    reason ProjectScope is a two-state value rather than `list | None`."""
    scope = resolve_project_scope(_user())

    assert scope.unrestricted is False
    assert scope.ids == frozenset()


def test_a_user_sees_exactly_the_projects_they_are_a_member_of() -> None:
    mine, theirs = uuid.uuid4(), uuid.uuid4()
    user = _user(grants={mine: _grant(mine, "viewer")})

    scope = resolve_project_scope(user)

    assert scope.ids == frozenset({mine})
    assert theirs not in scope.ids


def test_an_admin_sees_every_project() -> None:
    """is_admin administers the instance. It still never widens conversations."""
    assert resolve_project_scope(_user(is_admin=True)).unrestricted is True


def test_project_scope_all_is_still_constructible_deliberately() -> None:
    """`ProjectScope.all()` did not go away with phase 1 — the admin branch returns it.
    An empty scope must never be mistaken for it."""
    assert ProjectScope.all().unrestricted is True
    assert ProjectScope.of([]).unrestricted is False


def test_narrowing_an_unrestricted_scope_yields_exactly_the_requested_ids() -> None:
    """An unrestricted scope carries no ids, so a plain set intersection against it
    would return nothing. Narrowing has to read it as "everything" instead."""
    first, second = uuid.uuid4(), uuid.uuid4()

    narrowed = ProjectScope.all().narrowed_to([first, second])

    assert narrowed.unrestricted is False
    assert narrowed.ids == frozenset({first, second})


def test_narrowing_never_widens_a_restricted_scope() -> None:
    """The filter selects on a property unrelated to access, so it may only remove
    projects the resolver already allowed — never add one it did not."""
    allowed, forbidden = uuid.uuid4(), uuid.uuid4()

    narrowed = ProjectScope.of([allowed]).narrowed_to([allowed, forbidden])

    assert narrowed.ids == frozenset({allowed})


def test_narrowing_to_nothing_leaves_no_access() -> None:
    """An empty result is "none", never "all" — the same fail-closed rule `of` follows."""
    narrowed = ProjectScope.of([uuid.uuid4()]).narrowed_to([])

    assert narrowed.unrestricted is False
    assert narrowed.ids == frozenset()


# ── require_permission ───────────────────────────────────────────────────


def test_a_non_member_gets_404_not_403() -> None:
    """A 403 would confirm the project exists. Repository names are inventory of the
    organization's private codebases — spec §5."""
    with pytest.raises(HTTPException) as raised:
        require_permission(_user(), uuid.uuid4(), Permission.PROJECT_READ)

    assert raised.value.status_code == 404
    assert cast(dict[str, object], raised.value.detail)["code"] == "PROJECT_NOT_FOUND"


def test_a_member_whose_role_is_too_low_gets_403() -> None:
    """They can already see the project in their list, so hiding it would contradict
    what the UI just rendered."""
    project_id = uuid.uuid4()
    user = _user(grants={project_id: _grant(project_id, "viewer")})

    with pytest.raises(HTTPException) as raised:
        require_permission(user, project_id, Permission.PROJECT_DELETE)

    assert raised.value.status_code == 403
    assert cast(dict[str, object], raised.value.detail)["code"] == "INSUFFICIENT_ROLE"


def test_a_member_with_the_permission_passes() -> None:
    project_id = uuid.uuid4()
    user = _user(grants={project_id: _grant(project_id, "owner")})

    require_permission(user, project_id, Permission.PROJECT_DELETE)  # must not raise


def test_a_viewer_may_record_a_result() -> None:
    """docs/PRD.md §4.3:511 — recording is not gated; editing the expectation is."""
    project_id = uuid.uuid4()
    user = _user(grants={project_id: _grant(project_id, "viewer")})

    require_permission(user, project_id, Permission.RESULT_RECORD)  # must not raise

    with pytest.raises(HTTPException):
        require_permission(user, project_id, Permission.ITEM_EDIT)


@pytest.mark.parametrize("permission", list(Permission))
def test_an_admin_bypasses_every_project_permission(permission: Permission) -> None:
    """Safe only because no `conversation.*` permission exists to bypass —
    `tests/test_permissions.py::test_no_conversation_permission_exists`."""
    require_permission(_user(is_admin=True), uuid.uuid4(), permission)  # must not raise


# ── permissions_for / role_for ───────────────────────────────────────────


def test_permissions_for_returns_the_callers_effective_set() -> None:
    project_id = uuid.uuid4()
    user = _user(grants={project_id: _grant(project_id, "editor")})

    assert Permission.GENERATE_RUN.value in permissions_for(user, project_id)
    assert Permission.PROJECT_DELETE.value not in permissions_for(user, project_id)


def test_permissions_for_gives_an_admin_everything() -> None:
    assert permissions_for(_user(is_admin=True), uuid.uuid4()) == frozenset(
        p.value for p in Permission
    )


def test_permissions_for_a_non_member_is_empty() -> None:
    assert permissions_for(_user(), uuid.uuid4()) == frozenset()


def test_role_for_is_none_for_an_admin_with_no_membership() -> None:
    """The UI shows 'administrator', not a role it invented."""
    assert role_for(_user(is_admin=True), uuid.uuid4()) is None


def test_role_for_names_the_membership_when_there_is_one() -> None:
    project_id = uuid.uuid4()
    user = _user(grants={project_id: _grant(project_id, "editor")})

    assert role_for(user, project_id) == "editor"


# ── conversations are untouched ──────────────────────────────────────────


def test_conversation_owner_is_the_caller_even_for_an_admin() -> None:
    """docs/PRD.md §4.2 states conversation privacy without qualification. RBAC does
    not touch it, and no permission can reach it."""
    admin = _user(is_admin=True)

    assert resolve_conversation_owner(admin) == admin.id


# ── memberships_for ─────────────────────────────────────────────────────


def test_memberships_for_returns_real_grants_even_for_an_admin() -> None:
    """Unlike `resolve_project_scope`, this answers "where am I a member" — an admin's
    unrestricted read does not make them a member of anything."""
    project_id = uuid.uuid4()
    grant = ProjectGrant(project_id=project_id, role="editor", permissions=frozenset())
    admin = AuthenticatedUser(
        id=uuid.uuid4(),
        name="Admin",
        email="admin@example.com",
        is_admin=True,
        must_change_password=False,
        grants={project_id: grant},
    )
    nobody = AuthenticatedUser(
        id=uuid.uuid4(),
        name="Admin",
        email="other@example.com",
        is_admin=True,
        must_change_password=False,
    )

    assert memberships_for(admin) == [grant]
    assert memberships_for(nobody) == []
