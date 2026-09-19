"""The two admin-only reads over the audit trail.

`list` builds the table's rows; `get` builds the detail. Both are pure reads — this
service has no write method and must never grow one, per `.claude/rules/audit-trail.md`.
"""

import uuid
from typing import Protocol, cast

from fastapi import status
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import Mapped

from app.core.errors import AppError, ErrorCode
from app.models.audit import AuditEvent
from app.models.base import Base, SoftDeleteMixin
from app.models.checklist import ChecklistChangeSet, ChecklistItem, ChecklistModule
from app.models.conversation import Conversation
from app.models.membership import Role
from app.models.mock_data import MockDataChangeSet, MockDataDataset, MockDataRecord
from app.models.project import Project
from app.models.user import User
from app.repositories.audit_event import AuditEventRepository
from app.schemas.audit import (
    AuditEventCurrent,
    AuditEventListQuery,
    AuditEventResponse,
    AuditEventSummary,
)
from app.schemas.pagination import PaginatedResponse

# Which model a `target_type` string names, for the "does it still exist" lookup in
# `get`. A `target_type` with no entry here (or `None`) reports `None` rather than
# `False` — "unknown" and "gone" are different answers and this table only knows one
# of them.
_TARGET_MODELS: dict[str, type[Base]] = {
    "user": User,
    "project": Project,
    "conversation": Conversation,
    "checklist_module": ChecklistModule,
    "checklist_item": ChecklistItem,
    "checklist_change_set": ChecklistChangeSet,
    "mock_data_dataset": MockDataDataset,
    "mock_data_change_set": MockDataChangeSet,
    "mock_data_record": MockDataRecord,
    "role": Role,
}


class _HasId(Protocol):
    """Structural shape needed by `_still_exists`. None of `_TARGET_MODELS`'s
    values share a common typed base beyond `Base`, which declares no `id`."""

    id: Mapped[uuid.UUID]


class AuditService:
    """Backs `GET /audit-events` and `GET /audit-events/{id}`."""

    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = AuditEventRepository(session)

    async def list(self, query: AuditEventListQuery) -> PaginatedResponse[AuditEventSummary]:
        """One page of the trail, newest first unless asked otherwise."""
        offset = (query.page - 1) * query.limit
        rows, total = await self.repo.page(
            limit=query.limit,
            offset=offset,
            event_type=query.event_type,
            actor_user_id=query.actor_user_id,
            project_id=query.project_id,
            outcome=query.outcome,
            occurred_from=query.occurred_from,
            occurred_to=query.occurred_to,
            search=query.search,
            descending=query.sort_direction != "asc",
        )
        items = [self._summary(row) for row in rows]
        return PaginatedResponse.build(items, page=query.page, limit=query.limit, total_count=total)

    async def get(self, event_id: uuid.UUID) -> AuditEventResponse:
        """One row in full, plus whether its actor and target still exist."""
        row = await self.repo.get(event_id)
        if row is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.AUDIT_EVENT_NOT_FOUND,
                "No such audit event.",
            )

        actor_still_active = (
            await self._still_exists(User, row.actor_user_id)
            if row.actor_user_id is not None
            else None
        )

        target_model = _TARGET_MODELS.get(row.target_type) if row.target_type else None
        target_still_exists = (
            await self._still_exists(target_model, row.target_id)
            if row.target_id is not None and target_model is not None
            else None
        )

        return AuditEventResponse(
            **self._summary(row).model_dump(),
            details=row.details,
            ip_address=row.ip_address,
            current=AuditEventCurrent(
                actor_still_active=actor_still_active,
                target_still_exists=target_still_exists,
            ),
        )

    async def _still_exists(self, model: type[Base], entity_id: uuid.UUID) -> bool:
        """Whether a live (non-soft-deleted) row with this id still exists.

        Not routed through `BaseRepository`: the target could be any of several
        models, and a repository per lookup would be one class per row for a check
        that is the same three lines every time.
        """
        model_with_id = cast(type[_HasId], model)
        statement = select(model_with_id.id).where(model_with_id.id == entity_id)
        if issubclass(model, SoftDeleteMixin):
            statement = statement.where(cast(type[SoftDeleteMixin], model).deleted_at.is_(None))
        result = await self.session.execute(statement)
        return result.scalar_one_or_none() is not None

    @staticmethod
    def _summary(row: AuditEvent) -> AuditEventSummary:
        changed = row.details.get("changed")
        changed_fields = sorted(changed) if isinstance(changed, dict) else []
        return AuditEventSummary(
            id=row.id,
            created_at=row.created_at,
            event_type=row.event_type,
            outcome=row.outcome,
            actor_user_id=row.actor_user_id,
            actor_email=row.actor_email,
            target_type=row.target_type,
            target_id=row.target_id,
            target_label=row.target_label,
            project_id=row.project_id,
            changed_fields=changed_fields,
        )
