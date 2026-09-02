"""Queries over `checklist_change_sets`.

Unscoped by `ProjectScope`, deliberately. A change set is always reached through its
module, and the module read is already scoped -- adding a second scoping site here
would be exactly the duplication `docs/PRD.md` 7 forbids.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.models.checklist import ChangeSetStatus, ChecklistChangeSet, ChecklistModule
from app.repositories.base import BaseRepository


class ChecklistChangeSetRepository(BaseRepository[ChecklistChangeSet]):
    """Reads and writes for change sets."""

    model = ChecklistChangeSet

    async def pending_for_module(self, module_id: uuid.UUID) -> ChecklistChangeSet | None:
        """The one change set awaiting a decision, if there is one.

        At most one can exist (spec 3.3), and `ix_checklist_change_sets_module_id_status`
        is what keeps this cheap -- it is read on every module detail request.
        """
        result = await self.session.execute(
            self.active_select()
            .where(
                ChecklistChangeSet.module_id == module_id,
                ChecklistChangeSet.status == ChangeSetStatus.PENDING.value,
            )
            .order_by(ChecklistChangeSet.created_at.desc())
            .limit(1)
        )
        return result.scalar_one_or_none()

    async def pending_module_ids(self, module_ids: list[uuid.UUID]) -> dict[uuid.UUID, uuid.UUID]:
        """Module id to pending change-set id, for the modules that have one."""
        if not module_ids:
            return {}
        result = await self.session.execute(
            select(ChecklistChangeSet.module_id, ChecklistChangeSet.id).where(
                ChecklistChangeSet.module_id.in_(module_ids),
                ChecklistChangeSet.status == ChangeSetStatus.PENDING.value,
                ChecklistChangeSet.deleted_at.is_(None),
            )
        )
        return {module_id: change_set_id for module_id, change_set_id in result.all()}

    async def list_for_module(
        self, module_id: uuid.UUID, *, limit: int
    ) -> list[ChecklistChangeSet]:
        """This module's change sets, newest first -- the audit trail (spec 2.1)."""
        result = await self.session.execute(
            self.active_select()
            .where(ChecklistChangeSet.module_id == module_id)
            .order_by(ChecklistChangeSet.created_at.desc(), ChecklistChangeSet.id.asc())
            .limit(limit)
        )
        return list(result.scalars().all())

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete every change set of a module. `updated_at` set explicitly."""
        result = await self.session.execute(
            update(ChecklistChangeSet)
            .where(
                ChecklistChangeSet.module_id == module_id,
                ChecklistChangeSet.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every change set of every module of a project.

        A subquery over `checklist_modules` rather than a join: `checklist_change_sets`
        does not carry `project_id`, and denormalising it here would buy nothing --
        nothing filters change sets by project except this cascade.
        """
        modules = select(ChecklistModule.id).where(ChecklistModule.project_id == project_id)
        result = await self.session.execute(
            update(ChecklistChangeSet)
            .where(
                ChecklistChangeSet.module_id.in_(modules),
                ChecklistChangeSet.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
