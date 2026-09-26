"""The notification record, its per-recipient deliveries, and per-user preferences.

**`notification_events` carries neither mixin, and it is not append-only.** No
`updated_at`, because an occurrence is never mutated. No `deleted_at`, because nobody
soft-deletes a notification and `BaseRepository.active_select()` would be filtering a
column that is always `NULL`. Unlike `audit_events`, which shares those two omissions,
these rows *are* hard-deleted — by retention. `audit_events` is append-only because it
is the record; this is a nudge with a shelf life, and claiming append-only for it
would be claiming a guarantee the retention prune breaks every minute.

**`notifications.in_app_visible` is a preference snapshot, not a join.** A row is
written for every resolved recipient regardless of preference, because the row *is*
the per-`(user, event)` record and Phase 2.4's email is a delivery attempt against it
— suppressing the row would leave a user who muted in-app but wants email with nothing
to email against. See `.claude/rules/notifications.md`.

**`notifications.email_state` is the same kind of snapshot, taken at the same moment.**
`NotificationFanout` sets it to `"pending"` when mail is on and the recipient's email
preference for this event is on, and leaves it `NULL` otherwise — mail was off, or this
recipient turned this event's email off, at the moment the event happened. `NULL` means
email was never in play for this row; it is not a queue state a later worker advances
out of. Phase 2.4's outbox drains the `"pending"` rows.
"""

import uuid
from datetime import datetime
from typing import Literal

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    SmallInteger,
    String,
    UniqueConstraint,
    func,
    text,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.dialects.postgresql import UUID as PgUUID
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampMixin

EmailState = Literal["pending", "sent", "failed", "skipped"]


class NotificationEvent(Base):
    """One row per occurrence. Recipients hang off it."""

    __tablename__ = "notification_events"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    # NULL means *no authenticated actor* — a finished index has no actor, nobody did
    # it, a job did. Same reasoning as `audit_events.actor_user_id`: fabricating one
    # would record a lie.
    actor_user_id: Mapped[uuid.UUID | None] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=True
    )
    project_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("projects.id"), nullable=False
    )

    target_type: Mapped[str | None] = mapped_column(String(32), nullable=True)
    # Deliberately not a foreign key: the row it points at may be gone, and an FK
    # would either block that delete or cascade away the notification of it.
    target_id: Mapped[uuid.UUID | None] = mapped_column(PgUUID(as_uuid=True), nullable=True)

    details: Mapped[dict[str, object]] = mapped_column(JSONB, nullable=False, default=dict)

    __table_args__ = (
        Index("ix_notification_events_created_at", "created_at"),
        Index("ix_notification_events_event_type", "event_type"),
        Index("ix_notification_events_project_id", "project_id"),
    )


class Notification(Base):
    """One row per recipient. This is where read state lives."""

    __tablename__ = "notifications"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    # CASCADE is the right answer exactly here: a delivery has no meaning without its
    # event, and retention deletes both for the same reason at the same moment.
    event_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True),
        ForeignKey("notification_events.id", ondelete="CASCADE"),
        nullable=False,
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )

    in_app_visible: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    read_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    # --- Email delivery (Phase 2.4) ------------------------------------------------
    # A delivery attempt against this row, not a second record (spec §5.2). NULL
    # `email_state` means email was never in play for this recipient: mail was off, or
    # their email preference for this event was off, at the moment the event happened.
    email_state: Mapped[str | None] = mapped_column(String(16), nullable=True)
    email_attempts: Mapped[int] = mapped_column(
        SmallInteger, nullable=False, default=0, server_default=text("0")
    )
    email_claimed_until: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    email_sent_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)

    __table_args__ = (
        # The deduplication boundary `docs/PRD.md` §2.1 names by hand.
        UniqueConstraint("event_id", "user_id", name="uq_notifications_event_id_user_id"),
        # The polled unread count reads nothing but this.
        Index(
            "ix_notifications_unread",
            "user_id",
            postgresql_where="read_at IS NULL AND in_app_visible",
        ),
        Index("ix_notifications_user_id_created_at", "user_id", "created_at"),
        # What the outbox drain scans: rows waiting to be sent.
        Index(
            "ix_notifications_email_pending",
            "created_at",
            postgresql_where=text("email_state = 'pending'"),
        ),
    )


class NotificationPreference(TimestampMixin, Base):
    """One row per `(user, event_type)` the user has an opinion about.

    **Rows are sparse and absence means on.** No backfill for existing users, and a
    twelfth event type added later is on for everybody with no data migration. The
    failure direction is "you were told about something new", not "the feature
    silently did nothing for everyone who predates it".
    """

    __tablename__ = "notification_preferences"

    id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), primary_key=True, default=uuid.uuid4
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        PgUUID(as_uuid=True), ForeignKey("users.id"), nullable=False
    )
    event_type: Mapped[str] = mapped_column(String(64), nullable=False)

    in_app: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)
    # Read at fan-out time by Phase 2.4 to decide `notifications.email_state`. Shipping the
    # column ahead of that is what kept 2.4 additive: it added a sender, not a schema change,
    # a settings screen and a mail path at once.
    email: Mapped[bool] = mapped_column(Boolean, nullable=False, default=True)

    __table_args__ = (
        UniqueConstraint(
            "user_id", "event_type", name="uq_notification_preferences_user_id_event_type"
        ),
    )
