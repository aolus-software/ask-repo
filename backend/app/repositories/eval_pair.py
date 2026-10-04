"""Queries over `eval_pairs`. Pairs are never updated except for `excluded_at`."""

import uuid
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.eval import EvalPair, EvalSet
from app.repositories.base import BaseRepository


class EvalPairRepository(BaseRepository[EvalPair]):
    """A set's pairs."""

    model = EvalPair

    async def list_for_set(self, set_id: uuid.UUID, *, include_excluded: bool) -> list[EvalPair]:
        """A set's pairs in position order; optionally only the ones a run answers."""
        statement = self.active_select().where(EvalPair.set_id == set_id)
        if not include_excluded:
            statement = statement.where(EvalPair.excluded_at.is_(None))
        result = await self.session.execute(statement.order_by(EvalPair.position))
        return list(result.scalars().all())

    async def add_many(self, pairs: list[EvalPair]) -> None:
        """Insert a generated set's pairs in one flush."""
        self.session.add_all(pairs)
        await self.session.flush()

    async def soft_delete_for_set(self, set_id: uuid.UUID) -> int:
        """Soft-delete every pair of a set."""
        result = await self.session.execute(
            update(EvalPair)
            .where(EvalPair.set_id == set_id, EvalPair.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every pair of every set of a project."""
        sets = select(EvalSet.id).where(EvalSet.project_id == project_id)
        result = await self.session.execute(
            update(EvalPair)
            .where(EvalPair.set_id.in_(sets), EvalPair.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
