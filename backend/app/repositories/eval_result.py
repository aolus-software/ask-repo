"""Queries over `eval_results`: a run's per-pair outcomes."""

import uuid
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.eval import EvalResult, EvalRun
from app.repositories.base import BaseRepository


class EvalResultRepository(BaseRepository[EvalResult]):
    """A run's per-pair outcomes."""

    model = EvalResult

    async def pair_ids_for_run(self, run_id: uuid.UUID) -> set[uuid.UUID]:
        """Pairs this run already answered -- what makes a redelivered run cheap."""
        result = await self.session.execute(
            select(EvalResult.pair_id).where(
                EvalResult.run_id == run_id, EvalResult.deleted_at.is_(None)
            )
        )
        return set(result.scalars().all())

    async def list_for_run(self, run_id: uuid.UUID) -> list[EvalResult]:
        """Every result of a run."""
        result = await self.session.execute(self.active_select().where(EvalResult.run_id == run_id))
        return list(result.scalars().all())

    async def soft_delete_for_runs_of_set(self, set_id: uuid.UUID) -> int:
        """Soft-delete every result of every run of a set."""
        runs = select(EvalRun.id).where(EvalRun.set_id == set_id)
        result = await self.session.execute(
            update(EvalResult)
            .where(EvalResult.run_id.in_(runs), EvalResult.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every result of every run of a project."""
        runs = select(EvalRun.id).where(EvalRun.project_id == project_id)
        result = await self.session.execute(
            update(EvalResult)
            .where(EvalResult.run_id.in_(runs), EvalResult.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
