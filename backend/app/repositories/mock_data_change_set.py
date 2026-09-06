"""Queries over `mock_data_change_sets`.

Unscoped by `ProjectScope`, like `ChecklistChangeSetRepository`: a change set is always
reached through its already-scoped module.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.models.checklist import ChangeSetStatus, ChecklistModule
from app.models.mock_data import MockDataChangeSet
from app.repositories.base import BaseRepository


class MockDataChangeSetRepository(BaseRepository[MockDataChangeSet]):
    """Reads and writes for mock-data change sets."""

    model = MockDataChangeSet

    async def pending_for_module(self, module_id: uuid.UUID) -> MockDataChangeSet | None:
        """The one change set awaiting a decision, if there is one."""
        result = await self.session.execute(
            self.active_select()
            .where(
                MockDataChangeSet.checklist_module_id == module_id,
                MockDataChangeSet.status == ChangeSetStatus.PENDING.value,
            )
            .order_by(MockDataChangeSet.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def list_for_module(self, module_id: uuid.UUID, *, limit: int) -> list[MockDataChangeSet]:
        """This module's mock-data change sets, newest first."""
        result = await self.session.execute(
            self.active_select()
            .where(MockDataChangeSet.checklist_module_id == module_id)
            .order_by(MockDataChangeSet.created_at.desc(), MockDataChangeSet.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete every mock-data change set of a module."""
        result = await self.session.execute(
            update(MockDataChangeSet)
            .where(
                MockDataChangeSet.checklist_module_id == module_id,
                MockDataChangeSet.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every mock-data change set of every module of a project."""
        modules = select(ChecklistModule.id).where(ChecklistModule.project_id == project_id)
        result = await self.session.execute(
            update(MockDataChangeSet)
            .where(
                MockDataChangeSet.checklist_module_id.in_(modules),
                MockDataChangeSet.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
