"""The permission catalogue, and what each system role may do.

`Permission` is the **source of truth for which permissions exist**. `role_permissions`
rows reference these values; they do not define them. Anchoring existence in code makes
one class of mistake unrepresentable: if existence lived in a table, deleting a row
would make every check site ask for something that does not exist, and the fail-safe
answer — deny — would let one `DELETE` brick project deletion instance-wide.

**There is no conversation permission, and its absence is load-bearing.** An admin
bypasses every permission here (`app.core.access.require_permission`), which is safe
only because nothing here can reach a conversation. `docs/PRD.md` §4.2 states
conversation privacy without qualification; `tests/test_permissions.py` fails if a
`conversation.*` member is ever added.
"""

from dataclasses import dataclass
from enum import StrEnum


class Permission(StrEnum):
    """Every capability a project role can carry. Values are a wire contract —
    they appear in `GET /permissions` and in `ProjectResponse.permissions`."""

    PROJECT_READ = "project.read"
    PROJECT_UPDATE = "project.update"
    PROJECT_DELETE = "project.delete"
    PROJECT_REINDEX = "project.reindex"

    QUESTION_ASK = "question.ask"

    CHECKLIST_READ = "checklist.read"
    MODULE_CREATE = "module.create"
    MODULE_EDIT = "module.edit"
    MODULE_DELETE = "module.delete"
    GENERATE_RUN = "generate.run"
    CHANGESET_APPLY = "changeset.apply"
    ITEM_EDIT = "item.edit"
    RESULT_RECORD = "result.record"

    MOCKDATA_READ = "mockdata.read"
    MOCKDATA_EDIT = "mockdata.edit"

    MEMBERSHIP_READ = "membership.read"
    MEMBERSHIP_GRANT = "membership.grant"
    MEMBERSHIP_REVOKE = "membership.revoke"


@dataclass(frozen=True, slots=True)
class PermissionGroup:
    """One section of the role-matrix UI. Labels live here rather than being derived
    by splitting on `.` in the client, so the client needs no copy of the catalogue."""

    label: str
    permissions: tuple[Permission, ...]


PERMISSION_GROUPS: tuple[PermissionGroup, ...] = (
    PermissionGroup(
        "Project",
        (
            Permission.PROJECT_READ,
            Permission.PROJECT_UPDATE,
            Permission.PROJECT_DELETE,
            Permission.PROJECT_REINDEX,
        ),
    ),
    PermissionGroup("Questions", (Permission.QUESTION_ASK,)),
    PermissionGroup(
        "QA Checklist",
        (
            Permission.CHECKLIST_READ,
            Permission.MODULE_CREATE,
            Permission.MODULE_EDIT,
            Permission.MODULE_DELETE,
            Permission.GENERATE_RUN,
            Permission.CHANGESET_APPLY,
            Permission.ITEM_EDIT,
            Permission.RESULT_RECORD,
        ),
    ),
    PermissionGroup("Mock data", (Permission.MOCKDATA_READ, Permission.MOCKDATA_EDIT)),
    PermissionGroup(
        "Membership",
        (
            Permission.MEMBERSHIP_READ,
            Permission.MEMBERSHIP_GRANT,
            Permission.MEMBERSHIP_REVOKE,
        ),
    ),
)


VIEWER_NAME = "viewer"
EDITOR_NAME = "editor"
OWNER_NAME = "owner"

# `result.record` sits with viewer deliberately: `docs/PRD.md` §4.3:511 decided that
# editing a test is gated and recording a result is not, "otherwise the cheapest way
# to make a failing test pass is to edit the expectation". A viewer is a tester.
_VIEWER: frozenset[Permission] = frozenset(
    {
        Permission.PROJECT_READ,
        Permission.QUESTION_ASK,
        Permission.CHECKLIST_READ,
        Permission.MOCKDATA_READ,
        Permission.MEMBERSHIP_READ,
        Permission.RESULT_RECORD,
    }
)

_EDITOR: frozenset[Permission] = _VIEWER | {
    Permission.MODULE_CREATE,
    Permission.MODULE_EDIT,
    Permission.MODULE_DELETE,
    Permission.GENERATE_RUN,
    Permission.CHANGESET_APPLY,
    Permission.ITEM_EDIT,
    Permission.MOCKDATA_EDIT,
}

_OWNER: frozenset[Permission] = _EDITOR | {
    Permission.PROJECT_UPDATE,
    Permission.PROJECT_DELETE,
    Permission.PROJECT_REINDEX,
    Permission.MEMBERSHIP_GRANT,
    Permission.MEMBERSHIP_REVOKE,
}

SYSTEM_ROLES: dict[str, frozenset[Permission]] = {
    VIEWER_NAME: _VIEWER,
    EDITOR_NAME: _EDITOR,
    OWNER_NAME: _OWNER,
}

SYSTEM_ROLE_DESCRIPTIONS: dict[str, str] = {
    VIEWER_NAME: "Read the project, ask questions, and record test results.",
    EDITOR_NAME: "Everything a viewer can do, plus authoring checklists and mock data.",
    OWNER_NAME: "Full control, including deleting the project and managing members.",
}
