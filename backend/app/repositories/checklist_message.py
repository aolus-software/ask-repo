"""Queries over `checklist_messages` -- the module's shared refinement chat.

Shared, not private: every authenticated user reads every module's history, because
the chat is the justification record for a shared document (spec 2.4). There is
therefore no owner parameter anywhere in this module, and that absence is the design.

Unscoped by `ProjectScope` for the same reason as `checklist_change_set.py`: a message
is always reached through its module, and the module read is already scoped.
"""

import uuid
from typing import Any, cast

from sqlalchemy import CursorResult, func, select, update

from app.models.checklist import ChecklistMessage, ChecklistModule
from app.repositories.base import BaseRepository


class ChecklistMessageRepository(BaseRepository[ChecklistMessage]):
    """Reads and writes for a module's chat."""

    model = ChecklistMessage

    async def _latest(self, module_id: uuid.UUID, *, limit: int) -> list[ChecklistMessage]:
        """The most recent `limit` messages of a module's chat, oldest first.

        Selected newest-first so the database does the limiting, then reversed --
        capping on `created_at.asc()` would keep the chat's *oldest* messages and
        permanently hide everything recent once a module's history passes the cap.

        **Ordering rests on `created_at` being distinct per message**, exactly as it
        does for `ConversationRepository.recent_turns`: a turn's question and answer
        are committed in separate transactions -- the question in `prepare_turn`, the
        assistant row in a shielded finalise -- so Postgres `now()` advances between
        them. The `id` tiebreaker does not save this otherwise, since ids are `uuid4`
        and sort randomly rather than by insertion.
        """
        if limit <= 0:
            return []
        result = await self.session.execute(
            self.active_select()
            .where(ChecklistMessage.module_id == module_id)
            .order_by(ChecklistMessage.created_at.desc(), ChecklistMessage.id.desc())
            .limit(limit)
        )
        return list(reversed(result.scalars().all()))

    async def list_for_module(self, module_id: uuid.UUID, *, limit: int) -> list[ChecklistMessage]:
        """The module's chat as the panel renders it: the most recent `limit`
        messages, oldest first."""
        return await self._latest(module_id, limit=limit)

    async def recent_turns(self, module_id: uuid.UUID, *, limit: int) -> list[ChecklistMessage]:
        """The last `limit` messages of a module's chat, for the graph's history.

        Returns rows rather than `Turn`s deliberately, matching
        `ConversationRepository.recent_turns`: mapping to `Turn` also means dropping
        assistant turns that did not finish, which is a business rule and belongs in
        the service. It also keeps `app.rag` out of the persistence layer.
        """
        return await self._latest(module_id, limit=limit)

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete a module's whole chat. `updated_at` set explicitly (bulk)."""
        result = await self.session.execute(
            update(ChecklistMessage)
            .where(ChecklistMessage.module_id == module_id, ChecklistMessage.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every chat of every module of a project."""
        modules = select(ChecklistModule.id).where(ChecklistModule.project_id == project_id)
        result = await self.session.execute(
            update(ChecklistMessage)
            .where(ChecklistMessage.module_id.in_(modules), ChecklistMessage.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
