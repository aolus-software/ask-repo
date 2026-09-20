"""Writes to `notification_events`, and the retention prune.

**There is no `update` method**, because an occurrence is never mutated. There is one
delete path and it takes a cutoff and nothing else — no user filter, no event-type
filter — so the code that removes these rows cannot be aimed at anyone's entries. An
operator sets a window; nobody erases a row on demand.

Unlike `AuditEventRepository`, the prune here is not optional-by-default: see
`Settings.notification_retention_days`.
"""

from datetime import datetime
from typing import cast

from sqlalchemy import CursorResult, delete

from app.models.notification import NotificationEvent
from app.repositories.base import BaseRepository


class NotificationEventRepository(BaseRepository[NotificationEvent]):
    """Insert, and the prune."""

    model = NotificationEvent

    async def add(self, event: NotificationEvent) -> None:
        """Stage one event. Flushed by the fan-out, committed by the caller."""
        self.session.add(event)

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Hard-delete every event older than `cutoff`. Returns how many.

        `notifications.event_id` is `ON DELETE CASCADE`, so the deliveries go with
        them — a delivery has no meaning without its event, and both are deleted for
        the same reason at the same moment.
        """
        result = await self.session.execute(
            delete(NotificationEvent).where(NotificationEvent.created_at < cutoff)
        )
        return cast(CursorResult[object], result).rowcount
