"""The append-only record of who did what.

**This is the only table in the app outside both mixins, and both omissions are
load-bearing.** No `deleted_at`: `BaseRepository.active_select()` applies its filter
only when `SoftDeleteMixin` is present, so not carrying it means there is no
soft-delete path to reach these rows through — "append-only" stops being a convention
every future repository method must respect and becomes a property of the model. No
`updated_at`: `TimestampMixin` ships `onupdate=func.now()`, and a column recording a
mutation has no business on a row that is never mutated.

`docs/data.md`'s "every table except `refresh_tokens` and `messages` carries all
three" does not describe this one.
"""

import uuid
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, String, func
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base


class AuditEvent(Base):
    """One recorded action. Never updated, never soft-deleted."""

    __tablename__ = "audit_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)
    outcome: Mapped[str] = mapped_column(String(16), nullable=False, default="success")

    # NULL means *no authenticated actor* — a failed login against an unknown address,
    # or the seed-admins CLI. Nullable for the reason `project_memberships.granted_by`
    # is: fabricating an actor would record a lie in the one table whose purpose is
    # being trustworthy.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    # A snapshot, not a join. `users.email` is unique only where not deleted, so
    # deactivating an account frees the address for reuse — resolving at read time
    # would eventually attribute an old event to a new person.
    actor_email: Mapped[str | None] = mapped_column(String(320), nullable=True)

    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Deliberately not a foreign key: the row it points at may be gone, and an FK
    # would either block the delete or cascade away the record of it.
    target_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)
    # The core of the feature: a deleted project takes its name with it, so "who
    # deleted it" is only answerable if this row already holds *what* was deleted.
    # NULL for a conversation — its title derives from the user's question.
    target_label: Mapped[str | None] = mapped_column(String(255), nullable=True)

    project_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=True
    )
    ip_address: Mapped[str | None] = mapped_column(String(45), nullable=True)
    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)

    # None of these are partial: there is no `deleted_at` to filter, which is the one
    # place this table diverges from every other group in `docs/data.md`.
    __table_args__ = (
        Index("ix_audit_events_created_at", "created_at"),
        Index("ix_audit_events_actor_user_id", "actor_user_id"),
        Index("ix_audit_events_event_type", "event_type"),
        Index("ix_audit_events_project_id", "project_id"),
    )
