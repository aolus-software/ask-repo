"""The catalogue is data, so these are the only tests that can check it.

Every member must appear in exactly one of the two recipient mechanisms, must name a
target type, and must declare a detail allowlist. A member that is added and wired
where is invisible until someone tries to raise it.
"""

import pytest

from app.core.notifications import (
    ACTOR_EXCLUDED,
    DETAIL_FIELDS,
    DIRECT_EVENTS,
    RECIPIENT_PERMISSIONS,
    TARGET_TYPES,
    NotificationType,
    build_details,
)


def test_every_event_resolves_recipients_exactly_one_way() -> None:
    for event in NotificationType:
        permissioned = event in RECIPIENT_PERMISSIONS
        direct = event in DIRECT_EVENTS
        assert permissioned != direct, f"{event} must be permissioned xor direct"


def test_every_event_declares_a_target_type_and_detail_allowlist() -> None:
    for event in NotificationType:
        assert event in TARGET_TYPES, f"{event} names no target type"
        assert event in DETAIL_FIELDS, f"{event} declares no detail allowlist"


def test_actor_excluded_only_for_synchronous_actions() -> None:
    assert ACTOR_EXCLUDED == frozenset(
        {
            NotificationType.CHECKLIST_CHANGE_SET_APPLIED,
            NotificationType.CHECKLIST_CHANGE_SET_DISCARDED,
            NotificationType.MOCK_DATA_CHANGE_SET_APPLIED,
            NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED,
        }
    )


def test_membership_granted_is_the_only_direct_event() -> None:
    assert DIRECT_EVENTS == frozenset({NotificationType.MEMBERSHIP_GRANTED})


def test_build_details_accepts_allowlisted_keys() -> None:
    details = build_details(
        NotificationType.PROJECT_READY,
        {"projectName": "api", "fileCount": 12, "chunkCount": 340},
    )
    assert details == {"projectName": "api", "fileCount": 12, "chunkCount": 340}


def test_build_details_rejects_a_key_nobody_named() -> None:
    with pytest.raises(ValueError, match="repoUrl"):
        build_details(NotificationType.PROJECT_READY, {"repoUrl": "https://host/x.git"})


def test_build_details_replaces_an_oversized_payload_wholesale() -> None:
    details = build_details(NotificationType.PROJECT_READY, {"projectName": "x" * 4000})
    assert details == {"truncated": True}
