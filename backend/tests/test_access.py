"""The one function that answers "which projects may this caller read?".

`docs/PRD.md:359` makes single-point read scoping a success criterion, and these tests
are what give it something to point at before M1 exists. When phase 2 lands, the diff
should be this function's body and this file — nothing else.
"""

import uuid

from app.core.access import ProjectScope, resolve_project_scope
from app.core.middleware import AuthenticatedUser


def _user(*, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=uuid.uuid4(),
        name="Dev",
        email="dev@example.com",
        is_admin=is_admin,
        must_change_password=False,
    )


def test_phase_one_gives_a_regular_user_every_project() -> None:
    """Sharing is intended, not a leak — docs/PRD.md §4.1, SECURITY.md:34."""
    scope = resolve_project_scope(_user())

    assert scope.unrestricted is True


def test_phase_one_gives_an_admin_the_same_scope() -> None:
    """is_admin gates destructive operations, never reads."""
    assert resolve_project_scope(_user(is_admin=True)).unrestricted is True


def test_an_unrestricted_scope_carries_no_ids() -> None:
    """An id set alongside `unrestricted` would leave two sources of truth."""
    scope = ProjectScope.all()

    assert scope.ids == frozenset()


def test_a_restricted_scope_holds_exactly_the_given_ids() -> None:
    """The shape phase 2 will return."""
    first, second = uuid.uuid4(), uuid.uuid4()

    scope = ProjectScope.of([first, second, first])

    assert scope.unrestricted is False
    assert scope.ids == frozenset({first, second})


def test_a_restricted_scope_of_nothing_is_not_unrestricted() -> None:
    """The failure mode a `None` sentinel would have: empty must mean *no* access."""
    scope = ProjectScope.of([])

    assert scope.unrestricted is False
    assert scope.ids == frozenset()


def test_a_scope_is_immutable() -> None:
    """A caller must not be able to widen its own scope in place."""
    import dataclasses

    import pytest

    scope = ProjectScope.of([uuid.uuid4()])

    with pytest.raises(dataclasses.FrozenInstanceError):
        scope.unrestricted = True  # type: ignore[misc]  # asserting immutability
