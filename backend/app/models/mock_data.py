"""The QA Mock Data Generator tables.

Four tables, mirroring `app/models/checklist.py`'s shape for a second content type. The
key difference: `checklist_modules` already carries the checklist capability's own status
and generation lease, and a module may independently have a checklist, a mock dataset,
both, or neither -- so mock data cannot write those same columns without corrupting
whichever capability didn't just run. `mock_data_datasets` is therefore its own status/
lease row, created lazily on the first generation request, rather than new columns bolted
onto `checklist_modules`.

`mock_data_records` and `mock_data_change_sets` key directly to `checklist_modules.id`,
matching how `checklist_items`/`checklist_change_sets` key to their module rather than to
some intermediate row -- a record should survive even if the dataset row's own lifecycle
is ever reworked.
"""

import uuid
from datetime import datetime
from enum import StrEnum

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, SoftDeleteMixin, TimestampMixin


class MockDataDatasetStatus(StrEnum):
    """Where a module's mock dataset is in the generate-review cycle.

    Independent of `ChecklistModuleStatus` -- the same five names, a different state
    machine, because generating a dataset must not be observable as generating a
    checklist and vice versa.
    """

    EMPTY = "empty"
    GENERATING = "generating"
    REVIEW = "review"
    READY = "ready"
    FAILED = "failed"


class MockDataDataset(Base, TimestampMixin, SoftDeleteMixin):
    """One module's mock-data generation state: status, lease, and staleness marker."""

    __tablename__ = "mock_data_datasets"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checklist_module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False, unique=True
    )
    status: Mapped[str] = mapped_column(String(16), nullable=False)
    error: Mapped[str | None] = mapped_column(Text, nullable=True)
    # The project generation the last run read -- behind `project.active_generation`
    # means the repository was reindexed since this dataset was built, the same
    # staleness signal `checklist_modules.indexed_generation` gives the checklist.
    indexed_generation: Mapped[int | None] = mapped_column(Integer, nullable=True)
    last_generated_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )

    # --- The generation lease --- (mirrors `ChecklistModule`'s, independently owned)
    lease_owner: Mapped[str | None] = mapped_column(String(64), nullable=True)
    lease_expires_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_job_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)


class MockDataRecord(Base, TimestampMixin, SoftDeleteMixin):
    """One generated sample record: a dynamic field-key-to-value map."""

    __tablename__ = "mock_data_records"
    __table_args__ = (
        Index("ix_mock_data_records_module_id_created_at", "checklist_module_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checklist_module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False
    )
    # Every record in one generation batch shares the same key set -- validated at the
    # point operations are stored (`app/mockdata/operations.py`), not here.
    fields: Mapped[dict[str, str]] = mapped_column(JSONB, nullable=False)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )


class MockDataChangeSet(Base, TimestampMixin, SoftDeleteMixin):
    """A set of proposed record operations, pending a human decision.

    Shape and rules match `ChecklistChangeSet` exactly -- at most one `pending` per
    module's dataset, generation and chat are its only two producers, apply is the only
    writer of `mock_data_records`.
    """

    __tablename__ = "mock_data_change_sets"
    __table_args__ = (
        Index("ix_mock_data_change_sets_module_id_status", "checklist_module_id", "status"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checklist_module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False
    )
    # Values are `ChangeSetOrigin`/`ChangeSetStatus` from `app.models.checklist`, reused
    # rather than redefined: "generation vs chat" and "pending/applied/discarded" are not
    # checklist-specific concepts.
    origin: Mapped[str] = mapped_column(String(16), nullable=False)
    message_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("mock_data_messages.id"), nullable=True
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


class MockDataMessage(Base, TimestampMixin, SoftDeleteMixin):
    """One turn of a module's shared mock-data refinement chat.

    Shared like `ChecklistMessage`, and a distinct thread from it: refining the
    checklist and refining the mock dataset are different conversations about the same
    module.
    """

    __tablename__ = "mock_data_messages"
    __table_args__ = (
        Index("ix_mock_data_messages_module_id_created_at", "checklist_module_id", "created_at"),
    )

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    checklist_module_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("checklist_modules.id"), nullable=False
    )
    role: Mapped[str] = mapped_column(String(16), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    citations: Mapped[list[dict[str, object]] | None] = mapped_column(JSONB, nullable=True)
    model: Mapped[str | None] = mapped_column(String(255), nullable=True)
    finish_reason: Mapped[str | None] = mapped_column(String(32), nullable=True)
    created_by: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False, index=True
    )
