"""The permission catalogue and the system-role matrix.

These are the tests that make `docs/PRD.md` §4.2's conversation-privacy guarantee
structural rather than remembered — see `test_no_conversation_permission_exists`.
"""

from app.core.permissions import (
    PERMISSION_GROUPS,
    SYSTEM_ROLE_DESCRIPTIONS,
    SYSTEM_ROLES,
    Permission,
)


def test_no_conversation_permission_exists() -> None:
    """docs/PRD.md §4.2: conversations are private, with no admin bypass.

    An admin bypasses every permission in the catalogue (spec §4.3). That is safe
    only while no permission can reach a conversation. This test is the enforcement.
    """
    assert not [p for p in Permission if p.value.startswith("conversation.")]


def test_viewer_can_read_and_ask() -> None:
    viewer = SYSTEM_ROLES["viewer"]

    assert Permission.PROJECT_READ in viewer
    assert Permission.QUESTION_ASK in viewer
    assert Permission.CHECKLIST_READ in viewer


def test_viewer_can_record_a_result_but_not_edit_the_test() -> None:
    """docs/PRD.md §4.3:511 — 'editing a test is gated; recording a result is not'.

    Reversing this recreates the incentive that decision removed: a tester who
    cannot record a fail edits the expectation instead.
    """
    viewer = SYSTEM_ROLES["viewer"]

    assert Permission.RESULT_RECORD in viewer
    assert Permission.ITEM_EDIT not in viewer


def test_viewer_cannot_write_shared_content() -> None:
    viewer = SYSTEM_ROLES["viewer"]

    assert Permission.MODULE_CREATE not in viewer
    assert Permission.GENERATE_RUN not in viewer
    assert Permission.CHANGESET_APPLY not in viewer


def test_editor_cannot_delete_or_grant() -> None:
    editor = SYSTEM_ROLES["editor"]

    assert Permission.PROJECT_DELETE not in editor
    assert Permission.PROJECT_REINDEX not in editor
    assert Permission.MEMBERSHIP_GRANT not in editor


def test_roles_are_strictly_nested() -> None:
    """viewer ⊂ editor ⊂ owner. A role that removes a narrower role's permission
    would make 'higher role' meaningless and break the UI's role Select ordering."""
    assert SYSTEM_ROLES["viewer"] < SYSTEM_ROLES["editor"]
    assert SYSTEM_ROLES["editor"] < SYSTEM_ROLES["owner"]


def test_owner_holds_every_permission() -> None:
    assert SYSTEM_ROLES["owner"] == frozenset(Permission)


def test_every_system_role_has_a_description() -> None:
    assert set(SYSTEM_ROLE_DESCRIPTIONS) == set(SYSTEM_ROLES)


def test_every_permission_appears_in_exactly_one_group() -> None:
    """The matrix UI renders groups. A permission in no group is invisible and
    ungrantable; one in two groups renders twice with desynchronised checkboxes."""
    grouped = [p for group in PERMISSION_GROUPS for p in group.permissions]

    assert sorted(grouped) == sorted(Permission)
    assert len(grouped) == len(set(grouped))
