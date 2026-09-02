"""The QA Checklist tables — a reviewed test plan for the *indexed* application.

Four tables, and the split between them is the design. `checklist_items` is the
document; `checklist_change_sets` is the only thing that writes it. Generation and
chat are two producers of a change set, never two writers of an item, so a
regeneration is a diff against what exists rather than a fresh list that has to be
matched back against a tester's day of recorded results (spec 2.1).

Access follows `projects`, not `conversations`: every authenticated user reads
everything, `created_by` gates editing and deleting, and recording a *result* is open
to everyone (spec 2.4, 2.5).
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin

MAX_MODULE_NAME_CHARS = 120
MAX_SOURCE_PATH_CHARS = 512


class ChecklistModuleStatus(StrEnum):
    """Where a module is in the generate-review-record cycle."""

    EMPTY = "empty"
    GENERATING = "generating"
    REVIEW = "review"
    READY = "ready"
    FAILED = "failed"


class ChecklistItemStatus(StrEnum):
    """A tester's verdict on one test case.

    `BLOCKED` is a real state, distinct from `FAIL`: "could not run this because
    login is broken" is not the same finding as "this behaved wrongly", and without
    the value testers record it as a failure and corrupt the pass rate (spec 3.2).
    """

    UNTESTED = "untested"
    PASS = "pass"
    FAIL = "fail"
    BLOCKED = "blocked"


class ChecklistItemSource(StrEnum):
    """Where the test case came from."""

    GENERATED = "generated"
    MANUAL = "manual"


class ChangeSetOrigin(StrEnum):
    """Which of the two producers emitted this change set."""

    GENERATION = "generation"
    CHAT = "chat"


class ChangeSetStatus(StrEnum):
    """Whether a human has decided about this change set yet."""

    PENDING = "pending"
    APPLIED = "applied"
    DISCARDED = "discarded"


class ChecklistModule(Base, TimestampMixin, SoftDeleteMixin):
    """One named slice of a repository: the unit of generation and of review."""

    __tablename__ = "checklist_modules"
    __table_args__ = (
        Index("ix_checklist_modules_project_id_created_at", "project_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )

    name: Mapped[str] = mapped_column(String(MAX_MODULE_NAME_CHARS), nullable=False)
    source_path: Mapped[str] = mapped_column(String(MAX_SOURCE_PATH_CHARS), nullable=False)
    # String rather than a native Postgres enum, matching `Project.status`: adding a
    # value to a native enum needs a migration and a table lock.
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    # Scrubbed before it is written -- the module path is user-supplied and the
    # project's clone URL carries a PAT (spec 4.7, docs/PRD.md 9).
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The project generation the last run read. Behind `project.active_generation`
    # means the repository was reindexed since this checklist was built; the UI
    # surfaces that, nothing enforces it (spec 3.1).
    indexed_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- The generation lease (spec 4.5) ---
    #
    # Kafka is at-least-once, so this row -- not the offset and not the partition key
    # -- is what stops two workers generating the same module. `last_job_id` is what
    # separates "a redelivery of a job already finished" from "a new request", exactly
    # as it does on `projects`; without it a redelivery starts an unwanted second
    # generation the moment a finished job clears its lease.
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)


class ChecklistItem(Base, TimestampMixin, SoftDeleteMixin):
    """One test case: what is expected, and what a human observed."""

    __tablename__ = "checklist_items"
    __table_args__ = (
        # The grid's default ordering.
        Index("ix_checklist_items_module_id_feature_position", "module_id", "feature", "position"),
        # The status filter across modules, and the export.
        Index("ix_checklist_items_project_id_status", "project_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False
    )
    # Denormalised off `module_id` deliberately: the grid and the export both filter
    # by project across modules, and carrying it avoids a join on every list query.
    # Set at insert and never updated -- a module cannot move between projects.
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )

    # A column, not a table. A feature has no attributes beyond its name, and the grid
    # sorts on (module, feature, position) perfectly well as a column (spec 2.6).
    feature: Mapped[str] = mapped_column(String(MAX_MODULE_NAME_CHARS), nullable=False)
    test_name: Mapped[str] = mapped_column(Text, nullable=False)
    expected_result: Mapped[str] = mapped_column(Text, nullable=False)
    # Human only. A model asked to predict "what actually happens" writes a fluent
    # sentence indistinguishable from an observation, and a tester reading a
    # pre-filled result rubber-stamps it (spec 2.3).
    current_result: Mapped[str | None] = mapped_column(Text, nullable=True)
    status: Mapped[str] = mapped_column(String(16), nullable=False, index=True)
    notes: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The same `Citation` shape the answer stream uses, so the sources component
    # renders on a test case with no new component (spec 3.2).
    citations: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    source: Mapped[str] = mapped_column(String(16), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)

    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
    reviewed_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)


class ChecklistChangeSet(Base, TimestampMixin, SoftDeleteMixin):
    """A set of proposed operations, pending a human decision.

    At most one `pending` change set per module. A second generation while one is
    pending is refused with `409` rather than queued: two overlapping diffs against
    the same items would have to be rebased against each other, and there is no
    sensible automatic answer to that (spec 3.3).
    """

    __tablename__ = "checklist_change_sets"
    __table_args__ = (
        # Finding the pending change set -- the hot path on every module read.
        Index("ix_checklist_change_sets_module_id_status", "module_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False
    )
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    # The chat turn that produced it; null for generation.
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_messages.id"), nullable=True
    )
    summary: Mapped[str] = mapped_column(Text, nullable=False)
    operations: Mapped[list[dict[str, object]]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    resolved_by: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    resolved_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )


class ChecklistMessage(Base, TimestampMixin, SoftDeleteMixin):
    """One turn of the module's shared refinement chat.

    Shared, inverting `docs/PRD.md` 4.2 deliberately (spec 2.4): the chat is the
    justification record for a shared document, and a shared artifact whose change
    history is private is a shared artifact nobody can audit.

    Carries `deleted_at` where `messages` does not, because 5.1's exception for
    `messages` was justified by conversations being private and deleted wholesale
    with their parent.
    """

    __tablename__ = "checklist_messages"
    __table_args__ = (
        Index("ix_checklist_messages_module_id_created_at", "module_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Who spoke. Every authenticated user may read (spec 2.4).
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
