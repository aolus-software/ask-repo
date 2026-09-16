"""Queries over `audit_events`.

**There is no `update` method and there must never be one.** The table is append-only
(`.claude/rules/audit-trail.md`), and the single delete path below is driven by a
cutoff and nothing else — no actor filter, no event-type filter — so it cannot be
aimed at anyone's entries. An operator sets a window; nobody erases a row.
"""

import uuid
from datetime import datetime

from sqlalchemy import Select, delete, func, or_, select

from app.models.audit import AuditEvent
from app.repositories.base import BaseRepository


class AuditEventRepository(BaseRepository[AuditEvent]):
    """Reads for the admin routes, and the retention prune."""

    model = AuditEvent

    def _filtered(
        self,
        *,
        event_type: str | None,
        actor_user_id: uuid.UUID | None,
        project_id: uuid.UUID | None,
        outcome: str | None,
        occurred_from: datetime | None,
        occurred_to: datetime | None,
        search: str | None,
    ) -> Select[tuple[AuditEvent]]:
        """The shared WHERE for the page and its count, so the two cannot disagree."""
        statement = select(AuditEvent)
        if event_type is not None:
            statement = statement.where(AuditEvent.event_type == event_type)
        if actor_user_id is not None:
            statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
        if project_id is not None:
            statement = statement.where(AuditEvent.project_id == project_id)
        if outcome is not None:
            statement = statement.where(AuditEvent.outcome == outcome)
        if occurred_from is not None:
            statement = statement.where(AuditEvent.created_at >= occurred_from)
        if occurred_to is not None:
            statement = statement.where(AuditEvent.created_at <= occurred_to)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    AuditEvent.actor_email.ilike(pattern),
                    AuditEvent.target_label.ilike(pattern),
                )
            )
        return statement

    async def page(
        self,
        *,
        limit: int,
        offset: int,
        event_type: str | None = None,
        actor_user_id: uuid.UUID | None = None,
        project_id: uuid.UUID | None = None,
        outcome: str | None = None,
        occurred_from: datetime | None = None,
        occurred_to: datetime | None = None,
        search: str | None = None,
        descending: bool = True,
    ) -> tuple[list[AuditEvent], int]:
        """One page plus the total. `created_at` is the only ordering offered."""
        filters = {
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "project_id": project_id,
            "outcome": outcome,
            "occurred_from": occurred_from,
            "occurred_to": occurred_to,
            "search": search,
        }
        statement = self._filtered(**filters)
        order = AuditEvent.created_at.desc() if descending else AuditEvent.created_at.asc()
        rows = await self.session.execute(statement.order_by(order).limit(limit).offset(offset))

        count_statement = self._filtered(**filters).with_only_columns(
            func.count(AuditEvent.id)
        ).order_by(None)
        total = await self.session.execute(count_statement)

        return list(rows.scalars().all()), total.scalar_one()

    async def delete_older_than(self, cutoff: datetime) -> int:
        """Hard-delete every row created before `cutoff`. Returns how many went.

        A hard delete, not a soft one: the table carries no `deleted_at`, and a
        retention window that left the rows in place would not be a retention window.
        """
        result = await self.session.execute(
            delete(AuditEvent).where(AuditEvent.created_at < cutoff)
        )
        return result.rowcount or 0
