"""Reads and writes for `notifications` — the per-recipient rows.

Every read here is already scoped to one `user_id`, supplied by
`app.core.access.resolve_notification_owner`. No method takes a "whose" decision of
its own.
"""

import uuid
from datetime import UTC, datetime
from typing import cast

from sqlalchemy import CursorResult, Select, func, select, update

from app.models.notification import Notification, NotificationEvent
from app.repositories.base import BaseRepository


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
    ) -> tuple[list[tuple[Notification, NotificationEvent]], int]:
        """One page of the list, newest first, plus the unpaginated total."""
        statement = self._visible(user_id)
        if unread_only:
            statement = statement.where(Notification.read_at.is_(None))
        if project_id is not None:
            statement = statement.where(NotificationEvent.project_id == project_id)
        if event_type is not None:
            statement = statement.where(NotificationEvent.event_type == event_type)

        total = await self.session.execute(select(func.count()).select_from(statement.subquery()))
        rows = await self.session.execute(
            statement.order_by(Notification.created_at.desc())
            .offset((page - 1) * limit)
            .limit(limit)
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
