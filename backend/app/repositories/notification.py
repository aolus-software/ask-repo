"""Reads and writes for `notifications` — the per-recipient rows.

Every read here is already scoped to one `user_id`, supplied by
`app.core.access.resolve_notification_owner`. No method takes a "whose" decision of
its own.
"""

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import cast

from sqlalchemy import CursorResult, Select, func, or_, select, update

from app.models import User
from app.models.notification import EmailState, Notification, NotificationEvent
from app.repositories.base import BaseRepository


@dataclass(frozen=True)
class PendingEmail:
    """One claimed delivery, with just what the composer and the skip rules need."""

    notification_id: uuid.UUID
    attempts: int
    event_type: str
    target_type: str | None
    target_id: uuid.UUID | None
    project_id: uuid.UUID
    event_created_at: datetime
    to: str
    recipient_deactivated: bool


class NotificationRepository(BaseRepository[Notification]):
    """The bell, the list, and read state."""

    model = Notification

    async def add_all(self, rows: list[Notification]) -> None:
        """Stage every delivery for one event. Flushed by the fan-out."""
        self.session.add_all(rows)

    async def unread_count(self, user_id: uuid.UUID) -> int:
        """What the bell polls. Served by `ix_notifications_unread` alone."""
        result = await self.session.execute(
            select(func.count())
            .select_from(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
                Notification.in_app_visible.is_(True),
            )
        )
        return result.scalar_one()

    def _visible(self, user_id: uuid.UUID) -> Select[tuple[Notification, NotificationEvent]]:
        """This user's visible deliveries, joined to what they are about.

        `in_app_visible` is the preference *snapshot* taken at fan-out. Filtering on
        it here rather than joining to `notification_preferences` is what keeps the
        polled path off a join, and is why changing a preference does not retroactively
        reveal or hide what already happened.
        """
        return (
            select(Notification, NotificationEvent)
            .join(NotificationEvent, NotificationEvent.id == Notification.event_id)
            .where(
                Notification.user_id == user_id,
                Notification.in_app_visible.is_(True),
            )
        )

    async def page(
        self,
        user_id: uuid.UUID,
        *,
        page: int,
        limit: int,
        unread_only: bool,
        project_id: uuid.UUID | None,
        event_type: str | None,
        descending: bool = True,
    ) -> tuple[list[tuple[Notification, NotificationEvent]], int]:
        """One page of the list, plus the unpaginated total.

        `descending=True` (the default, newest first) matches `NotificationListQuery`'s
        default `sort_direction`, the same shape `AuditEventRepository.page` uses.
        """
        statement = self._visible(user_id)
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        if project_id is not None:
            statement = statement.where(NotificationEvent.project_id == project_id)
        if event_type is not None:
            statement = statement.where(NotificationEvent.event_type == event_type)

        order = Notification.created_at.desc() if descending else Notification.created_at.asc()
        total = await self.session.execute(select(func.count()).select_from(statement.subquery()))
        rows = await self.session.execute(
            statement.order_by(order).offset((page - 1) * limit).limit(limit)
        )
        return [(n, e) for n, e in rows.all()], total.scalar_one()

    async def mark_read(self, user_id: uuid.UUID, notification_id: uuid.UUID) -> bool:
        """Mark one read. `False` means no such row *for this user*.

        The `user_id` predicate is in the `UPDATE` itself rather than in a prior read,
        so there is no window between checking ownership and writing.
        """
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.id == notification_id,
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
            )
            .values(read_at=datetime.now(UTC))
        )
        if cast(CursorResult[object], result).rowcount:
            return True
        # Already read is not "not found": the caller's intent is satisfied either way,
        # and reporting 404 for a row they can see would be a lie.
        existing = await self.session.execute(
            select(Notification.id).where(
                Notification.id == notification_id, Notification.user_id == user_id
            )
        )
        return existing.scalar_one_or_none() is not None

    async def mark_all_read(self, user_id: uuid.UUID) -> int:
        """Mark every visible unread row read. Returns how many.

        Takes no filter and no ids on purpose: "mark all read" means all, and a
        filtered variant would be a second semantics on one route.
        """
        result = await self.session.execute(
            update(Notification)
            .where(
                Notification.user_id == user_id,
                Notification.read_at.is_(None),
                Notification.in_app_visible.is_(True),
            )
            .values(read_at=datetime.now(UTC))
        )
        return cast(CursorResult[object], result).rowcount

    async def claim_pending_email(self, *, limit: int, lease: timedelta) -> list[PendingEmail]:
        """Lease up to `limit` pending rows, so no other drain sends them meanwhile.

        `SKIP LOCKED` lets two drains run side by side without waiting on each other;
        the lease is what stops a crashed drain's rows being lost — they come back when
        it expires. The caller commits, so the lease is visible before any send.
        """
        now = datetime.now(UTC)
        candidates = (
            select(Notification.id)
            .where(
                Notification.email_state == "pending",
                or_(
                    Notification.email_claimed_until.is_(None),
                    Notification.email_claimed_until < now,
                ),
            )
            .order_by(Notification.created_at)
            .limit(limit)
            .with_for_update(skip_locked=True)
        )
        claimed = await self.session.execute(
            update(Notification)
            .where(Notification.id.in_(candidates))
            .values(
                email_claimed_until=now + lease,
                email_attempts=Notification.email_attempts + 1,
            )
            .returning(Notification.id)
        )
        ids = list(claimed.scalars().all())
        if not ids:
            return []
        rows = await self.session.execute(
            select(
                Notification.id,
                Notification.email_attempts,
                NotificationEvent.event_type,
                NotificationEvent.target_type,
                NotificationEvent.target_id,
                NotificationEvent.project_id,
                NotificationEvent.created_at,
                User.email,
                User.deleted_at,
            )
            .join(NotificationEvent, NotificationEvent.id == Notification.event_id)
            .join(User, User.id == Notification.user_id)
            .where(Notification.id.in_(ids))
        )
        return [
            PendingEmail(
                notification_id=row[0],
                attempts=row[1],
                event_type=row[2],
                target_type=row[3],
                target_id=row[4],
                project_id=row[5],
                event_created_at=row[6],
                to=row[7],
                recipient_deactivated=row[8] is not None,
            )
            for row in rows.all()
        ]

    async def mark_email(self, notification_id: uuid.UUID, state: EmailState) -> None:
        """Record a terminal outcome: `sent`, `failed` or `skipped`.

        Guarded on `email_state == "pending"`: if this row's lease already expired and
        a second drain reclaimed and sent it, that second send's `mark_email` must not
        be allowed to overwrite the outcome this call is racing against. Without the
        guard, the loser of the race can still win the write.
        """
        values: dict[str, object] = {"email_state": state, "email_claimed_until": None}
        if state == "sent":
            values["email_sent_at"] = datetime.now(UTC)
        await self.session.execute(
            update(Notification)
            .where(Notification.id == notification_id, Notification.email_state == "pending")
            .values(**values)
        )
