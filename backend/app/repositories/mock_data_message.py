"""Queries over `mock_data_messages` -- a module's shared mock-data refinement chat.

Structurally identical to `ChecklistMessageRepository`: unscoped by `ProjectScope`,
reached only through its already-scoped module.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.models.checklist import ChecklistModule
from app.models.mock_data import MockDataMessage
from app.repositories.base import BaseRepository


class MockDataMessageRepository(BaseRepository[MockDataMessage]):
    """Reads and writes for a module's mock-data chat."""

    model = MockDataMessage

    async def _latest(self, module_id: uuid.UUID, *, limit: int) -> list[MockDataMessage]:
        """The most recent `limit` messages, oldest first (see `ChecklistMessageRepository`
        for why ordering rests on `created_at` being distinct per message)."""
        if limit <= 0:
            return []
        result = await self.session.execute(
            self.active_select()
            .where(MockDataMessage.checklist_module_id == module_id)
            .order_by(MockDataMessage.created_at.desc(), MockDataMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def list_for_module(self, module_id: uuid.UUID, *, limit: int) -> list[MockDataMessage]:
        """The module's mock-data chat as the panel renders it."""
        return await self._latest(module_id, limit=limit)

    async def recent_turns(self, module_id: uuid.UUID, *, limit: int) -> list[MockDataMessage]:
        """The last `limit` messages, for the graph's history."""
        return await self._latest(module_id, limit=limit)

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete a module's whole mock-data chat."""
        result = await self.session.execute(
            update(MockDataMessage)
            .where(
                MockDataMessage.checklist_module_id == module_id,
                MockDataMessage.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every mock-data chat of every module of a project."""
        modules = select(ChecklistModule.id).where(ChecklistModule.project_id == project_id)
        result = await self.session.execute(
            update(MockDataMessage)
            .where(
                MockDataMessage.checklist_module_id.in_(modules),
                MockDataMessage.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
