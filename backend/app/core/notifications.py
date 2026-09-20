"""What a notification may be about, who hears it, and what it may carry.

Three things live here that look like they belong in a database and deliberately do
not, for the reason `app/core/permissions.py` and `app/core/audit.py` both give: if
existence lived in a table, deleting a row would orphan every write site that names
it. **The catalogue** is a `StrEnum`. **The recipient map** is a literal, so the
question "who hears about this" has one answer per event in one place. **The detail
allowlist** is a literal per event, never a diff, so a new column on `projects` is
invisible to a notification until somebody names it here.

Read `.claude/rules/notifications.md` before adding a member to any of them.
"""

import json
from enum import StrEnum

from app.core.permissions import Permission

# `details` is rendered in a popover and a table row. A payload past this is replaced
# wholesale rather than written half-way, so a reader never mistakes a truncation for
# the record. Smaller than the audit table's 8 KB: nothing here carries a diff.
MAX_DETAILS_BYTES = 2048


class NotificationType(StrEnum):
    """Every event a notification can be about. Values are stored and are a wire
    contract — add members, never rename them."""

    # --- ingestion ----------------------------------------------------------
    PROJECT_READY = "project.ready"
    PROJECT_FAILED = "project.failed"
    PROJECT_REINDEX_FINISHED = "project.reindex.finished"
    PROJECT_REINDEX_FAILED = "project.reindex.failed"
    # --- checklist change sets ----------------------------------------------
    CHECKLIST_CHANGE_SET_PENDING = "checklist_change_set.pending"
    CHECKLIST_CHANGE_SET_APPLIED = "checklist_change_set.applied"
    CHECKLIST_CHANGE_SET_DISCARDED = "checklist_change_set.discarded"
    # --- mock data change sets ----------------------------------------------
    MOCK_DATA_CHANGE_SET_PENDING = "mock_data_change_set.pending"
    MOCK_DATA_CHANGE_SET_APPLIED = "mock_data_change_set.applied"
    MOCK_DATA_CHANGE_SET_DISCARDED = "mock_data_change_set.discarded"
    # --- membership ---------------------------------------------------------
    MEMBERSHIP_GRANTED = "membership.granted"


# Which permission a member must hold on the project to hear about this event.
#
# Narrowing by permission is the product decision `docs/PRD.md` §2.1 hands to this
# phase. A viewer told about a change set they cannot apply is noise, and noise is
# what trains people to stop reading the bell.
RECIPIENT_PERMISSIONS: dict[NotificationType, Permission] = {
    NotificationType.PROJECT_READY: Permission.PROJECT_READ,
    NotificationType.PROJECT_FAILED: Permission.PROJECT_REINDEX,
    NotificationType.PROJECT_REINDEX_FINISHED: Permission.PROJECT_READ,
    NotificationType.PROJECT_REINDEX_FAILED: Permission.PROJECT_REINDEX,
    NotificationType.CHECKLIST_CHANGE_SET_PENDING: Permission.CHANGESET_APPLY,
    NotificationType.CHECKLIST_CHANGE_SET_APPLIED: Permission.CHECKLIST_READ,
    NotificationType.CHECKLIST_CHANGE_SET_DISCARDED: Permission.CHECKLIST_READ,
    NotificationType.MOCK_DATA_CHANGE_SET_PENDING: Permission.CHANGESET_APPLY,
    NotificationType.MOCK_DATA_CHANGE_SET_APPLIED: Permission.MOCKDATA_READ,
    NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED: Permission.MOCKDATA_READ,
}

# Events whose recipient is named by the caller rather than resolved from membership.
#
# `membership.granted`'s recipient is the grantee, who by construction was not a
# member when the event was raised — resolving it from membership either misses them
# or sweeps in everybody else. This is a separate mechanism rather than a branch
# inside the general path, because a branch is how "we already have one recipient
# resolver" quietly becomes two.
DIRECT_EVENTS: frozenset[NotificationType] = frozenset({NotificationType.MEMBERSHIP_GRANTED})

# Events where the actor is dropped from the recipient set.
#
# Per-event, not global. Telling you about your own click is noise; telling you that
# the reindex you started twenty minutes ago has finished is the entire feature.
ACTOR_EXCLUDED: frozenset[NotificationType] = frozenset(
    {
        NotificationType.CHECKLIST_CHANGE_SET_APPLIED,
        NotificationType.CHECKLIST_CHANGE_SET_DISCARDED,
        NotificationType.MOCK_DATA_CHANGE_SET_APPLIED,
        NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED,
    }
)

# What `target_id` points at — the *screen the recipient has to reach*, not the row
# that changed. Both change-set families therefore target the checklist module:
# `mock_data_change_sets` keys directly to `checklist_modules.id`, and the Mock Data
# tab is part of `/checklist/[moduleId]` rather than a route of its own, so a change
# set's own id names nothing anyone can navigate to.
TARGET_TYPES: dict[NotificationType, str] = {
    NotificationType.PROJECT_READY: "project",
    NotificationType.PROJECT_FAILED: "project",
    NotificationType.PROJECT_REINDEX_FINISHED: "project",
    NotificationType.PROJECT_REINDEX_FAILED: "project",
    NotificationType.CHECKLIST_CHANGE_SET_PENDING: "checklist_module",
    NotificationType.CHECKLIST_CHANGE_SET_APPLIED: "checklist_module",
    NotificationType.CHECKLIST_CHANGE_SET_DISCARDED: "checklist_module",
    NotificationType.MOCK_DATA_CHANGE_SET_PENDING: "checklist_module",
    NotificationType.MOCK_DATA_CHANGE_SET_APPLIED: "checklist_module",
    NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED: "checklist_module",
    NotificationType.MEMBERSHIP_GRANTED: "project",
}

# The only keys each event may carry. Keys are `camelCase` as stored, so `ApiModel`
# has nothing to translate and the stored bytes match the wire.
#
# **These are display names, and they are safe in-app precisely because they are not
# safe in an email.** Every in-app recipient is a member who can already read both
# names on the screen behind the bell. Phase 2.4's composer reads `event_type` and
# `target_id` and never touches this payload — `docs/PRD.md` §2.1 says an email
# carries the event type and a link and nothing else.
#
# `project.failed` carries no error text: `Project.error` holds the scrubbed message
# and the project screen renders it. A second copy of clone-derived output buys
# nothing over a link.
DETAIL_FIELDS: dict[NotificationType, frozenset[str]] = {
    NotificationType.PROJECT_READY: frozenset({"projectName", "fileCount", "chunkCount"}),
    NotificationType.PROJECT_FAILED: frozenset({"projectName"}),
    NotificationType.PROJECT_REINDEX_FINISHED: frozenset(
        {"projectName", "fileCount", "chunkCount"}
    ),
    NotificationType.PROJECT_REINDEX_FAILED: frozenset({"projectName"}),
    NotificationType.CHECKLIST_CHANGE_SET_PENDING: frozenset(
        {"projectName", "moduleName", "operationCount"}
    ),
    NotificationType.CHECKLIST_CHANGE_SET_APPLIED: frozenset(
        {"projectName", "moduleName", "appliedCount"}
    ),
    NotificationType.CHECKLIST_CHANGE_SET_DISCARDED: frozenset({"projectName", "moduleName"}),
    NotificationType.MOCK_DATA_CHANGE_SET_PENDING: frozenset(
        {"projectName", "moduleName", "operationCount"}
    ),
    NotificationType.MOCK_DATA_CHANGE_SET_APPLIED: frozenset(
        {"projectName", "moduleName", "appliedCount"}
    ),
    NotificationType.MOCK_DATA_CHANGE_SET_DISCARDED: frozenset({"projectName", "moduleName"}),
    NotificationType.MEMBERSHIP_GRANTED: frozenset({"projectName", "roleName"}),
}


def build_details(event_type: NotificationType, values: dict[str, object]) -> dict[str, object]:
    """Validate a payload against this event's allowlist, and bound its size.

    Raises `ValueError` on a key nobody named. That is the whole enforcement: no
    `scrub` call here and none needed, because the fan-out is handed plain scalars a
    service chose, never a clone URL or a token, and `scrub` needs the secret in hand
    to replace it. A value can only reach `details` by being named above.
    """
    allowed = DETAIL_FIELDS[event_type]
    unexpected = sorted(set(values) - allowed)
    if unexpected:
        raise ValueError(f"{event_type} may not carry {', '.join(unexpected)}")
    if len(json.dumps(values).encode()) > MAX_DETAILS_BYTES:
        return {"truncated": True}
    return dict(values)
