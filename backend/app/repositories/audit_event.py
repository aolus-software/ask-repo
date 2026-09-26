"""Queries over `audit_events`.

**There is no `update` method and there must never be one.** The table is append-only
(`.claude/rules/audit-trail.md`), and the single delete path below is driven by a
cutoff and nothing else — no actor filter, no event-type filter — so it cannot be
aimed at anyone's entries. An operator sets a window; nobody erases a row.
"""

import uuid
from datetime import datetime, time, timedelta
from typing import Any, TypedDict, cast

from sqlalchemy import CursorResult, Select, delete, func, or_, select

from app.models.audit import AuditEvent
from app.repositories.base import BaseRepository


class _PageFilters(TypedDict):
    """Keyword shape shared by `_filtered`'s two callers in `page`.

    A plain `dict[str, ...]` built from mixed-type values loses each field's own
    type the moment it is unpacked back into keyword arguments, so `_filtered`
    would see every argument as the union of all of them. This TypedDict keeps
    the per-field types intact across the `**filters` unpack.
    """

    event_type: str | None
    actor_user_id: uuid.UUID | None
    project_id: uuid.UUID | None
    outcome: str | None
    occurred_from: datetime | None
    occurred_to: datetime | None
    search: str | None
    visible_project_ids: frozenset[uuid.UUID] | None


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
        visible_project_ids: frozenset[uuid.UUID] | None,
    ) -> Select[tuple[AuditEvent]]:
        """The shared WHERE for the page and its count, so the two cannot disagree."""
        statement = select(AuditEvent)
        if event_type is not None:
            statement = statement.where(AuditEvent.event_type == event_type)
        if actor_user_id is not None:
            statement = statement.where(AuditEvent.actor_user_id == actor_user_id)
        if project_id is not None:
            statement = statement.where(AuditEvent.project_id == project_id)
        if visible_project_ids is not None:
            # A narrowing applied on top of the access resolver's answer, never instead of
            # it: the caller passes `resolve_project_scope`'s ids. Rows with no project —
            # sign-ins, account events — are always visible to their own actor.
            statement = statement.where(
                or_(
                    AuditEvent.project_id.is_(None),
                    AuditEvent.project_id.in_(visible_project_ids),
                )
            )
        if outcome is not None:
            statement = statement.where(AuditEvent.outcome == outcome)
        if occurred_from is not None:
            statement = statement.where(AuditEvent.created_at >= occurred_from)
        if occurred_to is not None:
            # `<input type="date">` on the filter screen submits a bare calendar day
            # (`2026-09-16`), which pydantic parses as midnight. A `<=` comparison
            # against midnight excludes every event actually recorded that day, which
            # hides evidence on the one screen whose purpose is finding it. When the
            # value carries no time component we treat it as the *whole* day and
            # compare exclusively against the start of the next one instead.
            #
            # This is still an absolute-instant comparison against a value that was
            # picked as the operator's local calendar day: `created_at` is UTC, and
            # asyncpg accepts this naive datetime as UTC too, so an operator whose
            # local day does not align with UTC is off by the difference between the
            # two — a few hours, not a day. Fixing that needs the operator's timezone,
            # which this endpoint is not given.
            if occurred_to.time() == time.min:
                statement = statement.where(AuditEvent.created_at < occurred_to + timedelta(days=1))
            else:
                statement = statement.where(AuditEvent.created_at <= occurred_to)
        if search:
            pattern = f"%{search}%"
            statement = statement.where(
                or_(
                    AuditEvent.actor_email.ilike(pattern),
                    AuditEvent.target_label.ilike(pattern),
                    # A contains-scan over `ip_address` too would grow with the
                    # table, and an address is meaningfully searched by prefix or
                    # exact match rather than substring — an operator pastes in
                    # the address a failed login recorded, not a fragment of one.
                    # `ip_address` has no index of its own, so this stays a prefix
                    # match rather than an unbounded `%...%` scan.
                    AuditEvent.ip_address.ilike(f"{search}%"),
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
        visible_project_ids: frozenset[uuid.UUID] | None = None,
        descending: bool = True,
    ) -> tuple[list[AuditEvent], int]:
        """One page plus the total. `created_at` is the only ordering offered."""
        filters: _PageFilters = {
            "event_type": event_type,
            "actor_user_id": actor_user_id,
            "project_id": project_id,
            "outcome": outcome,
            "occurred_from": occurred_from,
            "occurred_to": occurred_to,
            "search": search,
            "visible_project_ids": visible_project_ids,
        }
        statement = self._filtered(**filters)
        order = AuditEvent.created_at.desc() if descending else AuditEvent.created_at.asc()
        rows = await self.session.execute(statement.order_by(order).limit(limit).offset(offset))

        count_statement = (
            self._filtered(**filters).with_only_columns(func.count(AuditEvent.id)).order_by(None)
        )
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
        # `execute` is typed as returning `Result`, which declares no `rowcount`; a
        # bulk DELETE really returns a `CursorResult`. Same cast as
        # `ProjectRepository.release` and its siblings.
        return cast(CursorResult[Any], result).rowcount
