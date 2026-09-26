"""The audit write path: what may be recorded, and the recorder that records it.

Two things live here that look like they belong in a database and deliberately do
not. **The catalogue** of event names is a `StrEnum`, not a table, for the reason
`app/core/permissions.py` gives for the permission catalogue: if existence lived in a
table, deleting a row would orphan every write site that names it. **The field
allowlist** is a literal per event, not a diff of the model's dirty attributes,
because a generic differ would start writing `password_hash` and `encrypted_pat` into
an operator-readable table the moment someone adds a column. A new column is invisible
to the trail until someone names it here, and that is the correct failure direction.

Read `.claude/rules/audit-trail.md` before adding a name to either.
"""

import json
import logging
import uuid
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Literal
from urllib.parse import urlsplit

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.models.audit import AuditEvent

logger = logging.getLogger(__name__)

# `details` is operator-readable and unbounded input would let one row crowd out the
# table it is meant to explain. A payload past this is replaced wholesale rather than
# written half-way, so a reader never mistakes a truncation for the record.
MAX_DETAILS_BYTES = 8192


class AuditEventType(StrEnum):
    """Every action the trail records. Values are stored and are a wire contract.

    Add members, never rename them — `tests/test_audit_coverage.py` asserts in both
    directions that each name here has a write site and each write site uses a name
    from here.
    """

    # --- auth ---------------------------------------------------------------
    AUTH_LOGIN_SUCCEEDED = "auth.login.succeeded"
    AUTH_LOGIN_FAILED = "auth.login.failed"
    AUTH_LOGOUT = "auth.logout"
    AUTH_PASSWORD_CHANGED = "auth.password.changed"
    AUTH_REFRESH_REPLAYED = "auth.refresh.replayed"
    AUTH_PASSWORD_RESET_REQUESTED = "auth.password_reset.requested"
    AUTH_PASSWORD_RESET_COMPLETED = "auth.password_reset.completed"
    AUTH_SESSION_REVOKED = "auth.session.revoked"
    # --- accounts -----------------------------------------------------------
    USER_CREATED = "user.created"
    USER_UPDATED = "user.updated"
    USER_DEACTIVATED = "user.deactivated"
    USER_PASSWORD_RESET = "user.password.reset"
    # --- projects -----------------------------------------------------------
    PROJECT_CREATED = "project.created"
    PROJECT_REINDEX_REQUESTED = "project.reindex.requested"
    PROJECT_DELETED = "project.deleted"
    # --- RBAC ---------------------------------------------------------------
    MEMBERSHIP_GRANTED = "membership.granted"
    MEMBERSHIP_ROLE_CHANGED = "membership.role_changed"
    MEMBERSHIP_REVOKED = "membership.revoked"
    ROLE_CREATED = "role.created"
    ROLE_UPDATED = "role.updated"
    ROLE_DELETED = "role.deleted"
    # --- checklist modules --------------------------------------------------
    CHECKLIST_MODULE_CREATED = "checklist_module.created"
    CHECKLIST_MODULE_UPDATED = "checklist_module.updated"
    CHECKLIST_MODULE_DELETED = "checklist_module.deleted"
    CHECKLIST_MODULE_GENERATION_REQUESTED = "checklist_module.generation.requested"
    # --- checklist items ----------------------------------------------------
    CHECKLIST_ITEM_CREATED = "checklist_item.created"
    CHECKLIST_ITEM_UPDATED = "checklist_item.updated"
    CHECKLIST_ITEM_RESULT_RECORDED = "checklist_item.result_recorded"
    CHECKLIST_ITEM_DELETED = "checklist_item.deleted"
    CHECKLIST_ITEM_RESULTS_CLEARED = "checklist_item.results_cleared"
    # --- checklist change sets ----------------------------------------------
    CHECKLIST_CHANGE_SET_APPLIED = "checklist_change_set.applied"
    CHECKLIST_CHANGE_SET_DISCARDED = "checklist_change_set.discarded"
    CHECKLIST_EXPORTED = "checklist.exported"
    # --- mock data ----------------------------------------------------------
    MOCK_DATA_GENERATION_REQUESTED = "mock_data.generation.requested"
    MOCK_DATA_CHANGE_SET_APPLIED = "mock_data_change_set.applied"
    MOCK_DATA_CHANGE_SET_DISCARDED = "mock_data_change_set.discarded"
    MOCK_DATA_RECORD_DELETED = "mock_data_record.deleted"
    MOCK_DATA_EXPORTED = "mock_data.exported"
    # --- conversations ------------------------------------------------------
    # Metadata only: no title, no message, no per-question row. See spec §1.4 and
    # `.claude/rules/audit-trail.md` — this is a deliberate narrowing of what
    # `docs/PRD.md` §4.2 previously stated without qualification.
    CONVERSATION_CREATED = "conversation.created"
    CONVERSATION_DELETED = "conversation.deleted"


# Which fields may appear in `changed`, per event. Keys are `camelCase` because that
# is how they are stored — `ApiModel` has nothing to translate on the way out, so the
# stored bytes match the wire.
CHANGED_FIELDS: dict[AuditEventType, frozenset[str]] = {
    AuditEventType.USER_CREATED: frozenset({"name", "email", "isAdmin", "mustChangePassword"}),
    # `email` and `mustChangePassword` are dropped here (never `mustChangePassword`,
    # never `email`): `UserUpdateRequest` carries only `name` and `isAdmin`
    # (`app/schemas/user.py`), so `PATCH /users/{id}` cannot write either. An
    # allowlist entry with no producer reads as documentation and is wrong in the
    # misleading direction (`.claude/rules/audit-trail.md`).
    AuditEventType.USER_UPDATED: frozenset({"name", "isAdmin"}),
    AuditEventType.PROJECT_CREATED: frozenset({"name", "repoUrlHost", "branch"}),
    AuditEventType.PROJECT_DELETED: frozenset({"name", "repoUrlHost"}),
    AuditEventType.MEMBERSHIP_GRANTED: frozenset({"roleName"}),
    AuditEventType.MEMBERSHIP_ROLE_CHANGED: frozenset({"roleName"}),
    AuditEventType.MEMBERSHIP_REVOKED: frozenset({"roleName"}),
    AuditEventType.ROLE_CREATED: frozenset({"name", "description", "permissions"}),
    AuditEventType.ROLE_UPDATED: frozenset({"name", "description", "permissions"}),
    AuditEventType.ROLE_DELETED: frozenset({"name", "permissions"}),
    AuditEventType.CHECKLIST_MODULE_CREATED: frozenset({"name", "sourcePath"}),
    AuditEventType.CHECKLIST_MODULE_UPDATED: frozenset({"name", "sourcePath"}),
    AuditEventType.CHECKLIST_MODULE_DELETED: frozenset({"name", "sourcePath"}),
    AuditEventType.CHECKLIST_ITEM_CREATED: frozenset({"feature", "testName"}),
    # `expectedResult` never appears here: it is model-authored prose derived from a
    # private repository, which the content ban forbids storing, and `audit_events`
    # has no project-deletion sweep so it would outlive the project it described.
    # `expectedResultChanged` records that the expectation moved without copying it.
    # `position` is dropped too -- `update()` never writes it, only `create()`'s
    # `next_position` call does, so the key had no producer.
    AuditEventType.CHECKLIST_ITEM_UPDATED: frozenset(
        {"feature", "testName", "expectedResultChanged"}
    ),
    # `currentResult` and `notes` are dropped for the same reason: `currentResult` is
    # a tester's free-text observation and `notes` is never written by `set_result`.
    # `currentResultChanged` is the boolean substitute.
    AuditEventType.CHECKLIST_ITEM_RESULT_RECORDED: frozenset({"status", "currentResultChanged"}),
    AuditEventType.CHECKLIST_ITEM_DELETED: frozenset({"feature", "testName"}),
}

# Immutable context that is not a change: flat keys beside `changed`.
CONTEXT_KEYS: dict[AuditEventType, frozenset[str]] = {
    AuditEventType.AUTH_LOGIN_SUCCEEDED: frozenset({"mustChangePassword"}),
    AuditEventType.AUTH_LOGIN_FAILED: frozenset({"unknownAccount"}),
    AuditEventType.AUTH_LOGOUT: frozenset({"scope"}),
    AuditEventType.AUTH_PASSWORD_CHANGED: frozenset({"forced"}),
    # `actor_user_id`/`actor_email` (top-level `AuditEntry` fields, populated from
    # `token.user_id`) name whose account was replayed against; `familyId` and
    # `revokedCount` stay here as context.
    AuditEventType.AUTH_REFRESH_REPLAYED: frozenset({"familyId", "revokedCount"}),
    # Follows `auth.login.failed`: the address is stored only when it matches a live
    # user, because people paste passwords into email fields.
    AuditEventType.AUTH_PASSWORD_RESET_REQUESTED: frozenset({"unknownAccount"}),
    AuditEventType.AUTH_PASSWORD_RESET_COMPLETED: frozenset({"revokedCount"}),
    # A user ending one of their own sessions from the profile. `current` separates
    # "signed this device out" from "signed another device out" — the second is the one
    # worth a responder's attention. No `changed` block: the event is its name.
    AuditEventType.AUTH_SESSION_REVOKED: frozenset({"familyId", "current", "revokedCount"}),
    AuditEventType.USER_CREATED: frozenset({"source"}),
    AuditEventType.USER_PASSWORD_RESET: frozenset({"forced"}),
    AuditEventType.PROJECT_CREATED: frozenset({"patSupplied"}),
    AuditEventType.PROJECT_REINDEX_REQUESTED: frozenset({"supersededGeneration"}),
    AuditEventType.PROJECT_DELETED: frozenset(
        {
            "fileCount",
            "chunkCount",
            "embeddingCollection",
            "conversationsDeleted",
            "checklistModulesDeleted",
        }
    ),
    AuditEventType.CHECKLIST_MODULE_DELETED: frozenset({"itemCount"}),
    AuditEventType.CHECKLIST_MODULE_GENERATION_REQUESTED: frozenset({"indexedGeneration"}),
    AuditEventType.CHECKLIST_ITEM_CREATED: frozenset({"origin"}),
    AuditEventType.CHECKLIST_ITEM_DELETED: frozenset({"hadRecordedResult"}),
    AuditEventType.CHECKLIST_ITEM_RESULTS_CLEARED: frozenset({"clearedCount", "filter"}),
    AuditEventType.CHECKLIST_CHANGE_SET_APPLIED: frozenset(
        {"origin", "operationsProposed", "operationsApplied"}
    ),
    AuditEventType.CHECKLIST_CHANGE_SET_DISCARDED: frozenset({"origin", "operationsProposed"}),
    # `projectCount` names how many distinct projects the export spanned, for the
    # turns `project_id` is `None` because the filter matched more than one -- see
    # `ChecklistItemService.export`.
    AuditEventType.CHECKLIST_EXPORTED: frozenset({"format", "rowCount", "filter", "projectCount"}),
    AuditEventType.MOCK_DATA_GENERATION_REQUESTED: frozenset({"indexedGeneration"}),
    AuditEventType.MOCK_DATA_CHANGE_SET_APPLIED: frozenset(
        {"origin", "operationsProposed", "operationsApplied"}
    ),
    AuditEventType.MOCK_DATA_CHANGE_SET_DISCARDED: frozenset({"origin", "operationsProposed"}),
    AuditEventType.MOCK_DATA_RECORD_DELETED: frozenset({"position"}),
    AuditEventType.MOCK_DATA_EXPORTED: frozenset({"format", "rowCount"}),
    AuditEventType.CONVERSATION_DELETED: frozenset({"messageCount"}),
}

type ChangedValue = str | bool | int | float | list[str] | None
# `context` alone may also carry a flat string-to-string map (the `filter` key on a
# bulk clear or export). `ChangedValue` stays scalars-and-lists-only: widening it to
# accept a `dict` would let `changed={"foo": ({...}, {...})}` typecheck, and no
# database column can store a dict-of-dicts -- the before/after renderer would print
# it as `[object Object]`.
type ContextValue = ChangedValue | dict[str, str]
type Outcome = Literal["success", "failure"]


def repo_url_host(url: str) -> str | None:
    """The hostname of a clone URL, with any embedded credentials dropped.

    A PAT rides in the userinfo of a clone URL, so this parses and keeps `hostname`
    rather than trimming a prefix: `urlsplit().hostname` excludes userinfo and the
    port by construction, which a string operation would have to be rewritten to keep
    true under a URL shape nobody anticipated.
    """
    try:
        return urlsplit(url).hostname
    except ValueError:
        return None


@dataclass(frozen=True, slots=True)
class AuditEntry:
    """One thing that happened, as plain data.

    Deliberately not an ORM object and never holding one: a recorder that cannot
    touch a `Session` cannot be made to re-read a row that is now soft-deleted, or to
    hold one open past the request. Write sites capture scalars into locals before
    mutating and hand a dict here.
    """

    event_type: AuditEventType
    outcome: Outcome = "success"
    actor_user_id: uuid.UUID | None = None
    actor_email: str | None = None
    target_type: str | None = None
    target_id: uuid.UUID | None = None
    target_label: str | None = None
    project_id: uuid.UUID | None = None
    ip_address: str | None = None
    # field -> (before, after). A create passes `None` for before, a delete for after.
    changed: dict[str, tuple[ChangedValue, ChangedValue]] = field(default_factory=dict)
    context: dict[str, ContextValue] = field(default_factory=dict)

    def details(self) -> dict[str, object]:
        """Build the stored payload, refusing anything the allowlist does not name.

        Raises `ValueError` rather than dropping the offending key: a silent drop
        would make an event look complete while missing the field somebody added it
        for. `AuditRecorder.record` catches it, so a programming error here is loud in
        the log and never a 500 for the user.
        """
        allowed_changed = CHANGED_FIELDS.get(self.event_type, frozenset())
        undeclared = set(self.changed) - allowed_changed
        if undeclared:
            raise ValueError(
                f"{self.event_type} may not record changed field(s): {sorted(undeclared)}"
            )

        allowed_context = CONTEXT_KEYS.get(self.event_type, frozenset())
        undeclared_context = set(self.context) - allowed_context
        if undeclared_context:
            raise ValueError(
                f"{self.event_type} may not record context key(s): {sorted(undeclared_context)}"
            )

        payload: dict[str, object] = dict(self.context)
        if self.changed:
            payload["changed"] = {
                name: {"before": before, "after": after}
                for name, (before, after) in self.changed.items()
            }

        if len(json.dumps(payload).encode()) > MAX_DETAILS_BYTES:
            return {"truncated": True}
        return payload


class AuditRecorder:
    """Writes one audit row, on its own session, and never raises.

    **Its own session** rather than the request-scoped one, so the write does not
    depend on when FastAPI closes the request's `AsyncExitStack` — the same reasoning
    `.claude/rules/rag.md` gives for the shielded termination write.

    **Never raises** is what makes "an audit failure cannot fail a user's action"
    structural rather than a promise every call site keeps. The accepted consequence,
    which `docs/superpowers/specs/2026-09-16-phase-2.2-audit-trail-design.md` §4.2
    states rather than hides: an action that commits and then crashes before this runs
    leaves no row, silently. The `WARNING` below is the fallback, and the log is not
    the record.
    """

    def __init__(self, sessionmaker: async_sessionmaker[AsyncSession]) -> None:
        self._sessionmaker = sessionmaker

    async def record(self, entry: AuditEntry) -> None:
        """Persist one entry. Swallows every `Exception`; logs what it swallowed."""
        try:
            details = entry.details()
            async with self._sessionmaker() as session:
                session.add(
                    AuditEvent(
                        event_type=entry.event_type.value,
                        outcome=entry.outcome,
                        actor_user_id=entry.actor_user_id,
                        actor_email=entry.actor_email,
                        target_type=entry.target_type,
                        target_id=entry.target_id,
                        target_label=entry.target_label,
                        project_id=entry.project_id,
                        ip_address=entry.ip_address,
                        details=details,
                    )
                )
                await session.commit()
        # Not `BaseException`: `CancelledError` is one, and a client that disconnected
        # should stop the turn rather than be audited into a dead session.
        except Exception:
            logger.warning("audit write failed for %s", entry.event_type, exc_info=True)
