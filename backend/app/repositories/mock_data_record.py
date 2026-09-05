"""Queries over `mock_data_records`.

Unscoped by `ProjectScope`, like `ChecklistItemRepository.list_for_module`: a record is
always reached through its already-scoped module.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.models.checklist import ChecklistModule
from app.models.mock_data import MockDataRecord
from app.repositories.base import BaseRepository


class MockDataRecordRepository(BaseRepository[MockDataRecord]):
    """Reads and writes for one module's generated sample records."""

    model = MockDataRecord

    async def list_for_module(self, module_id: uuid.UUID) -> list[MockDataRecord]:
        """Every live record of one module, oldest first — the order a generated batch was produced in."""
        result = await self.session.execute(
            self.active_select()
            .where(MockDataRecord.checklist_module_id == module_id)
            .order_by(MockDataRecord.created_at.asc(), MockDataRecord.id.asc())
        )
        return list(result.scalars().all())

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete every record of a module."""
        result = await self.session.execute(
            update(MockDataRecord)
            .where(
                MockDataRecord.checklist_module_id == module_id,
                MockDataRecord.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every record of every module of a project."""
        modules = select(ChecklistModule.id).where(ChecklistModule.project_id == project_id)
        result = await self.session.execute(
            update(MockDataRecord)
            .where(
                MockDataRecord.checklist_module_id.in_(modules),
                MockDataRecord.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
