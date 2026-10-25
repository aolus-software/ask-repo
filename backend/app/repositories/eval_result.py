"""Queries over `eval_results`: a run's per-pair outcomes."""

import uuid
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.models.eval import EvalPair, EvalResult, EvalRun, EvalVerdict
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

    async def tally_for_run(self, run_id: uuid.UUID) -> dict[str, int]:
        """The run's summary columns, computed from its committed result rows.

        Keys are `eval_runs` column names, so a caller can pass the dict straight to
        `EvalRunRepository.release`. A run with no results tallies zeros.
        """
        live = EvalResult.run_id == run_id, EvalResult.deleted_at.is_(None)
        row = (
            await self.session.execute(
                select(
                    func.count(),
                    func.count().filter(EvalResult.retrieval_hit.is_(True)),
                    func.count().filter(EvalResult.verdict == EvalVerdict.CORRECT.value),
                    func.count().filter(EvalResult.verdict == EvalVerdict.PARTIAL.value),
                    func.count().filter(EvalResult.verdict == EvalVerdict.WRONG.value),
                    func.count().filter(EvalResult.verdict == EvalVerdict.ERROR.value),
                ).where(*live)
            )
        ).one()
        return {
            "pairs_answered": row[0],
            "hits": row[1],
            "correct": row[2],
            "partial": row[3],
            "wrong": row[4],
            "errors": row[5],
        }

    async def list_for_run(self, run_id: uuid.UUID) -> list[EvalResult]:
        """Every result of a run, in the order its pairs sit in the set.

        A total order, so a screen polling a running run does not see rows reshuffle.
        """
        result = await self.session.execute(
            self.active_select()
            .join(EvalPair, EvalPair.id == EvalResult.pair_id)
            .where(EvalResult.run_id == run_id)
            .order_by(EvalPair.position, EvalResult.id)
        )
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
