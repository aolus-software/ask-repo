"""Queries over `eval_runs`, including the run lease.

The lease statements are the shared ones in `app/repositories/lease.py`; each method
here passes this table's status vocabulary and stages its own live event.
Unscoped by `ProjectScope`: access is decided in
`app/core/access.py`, and these methods filter only by ids they are handed.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.live.events import eval_run_event
from app.live.staging import stage_live_event
from app.models.eval import EvalRun, EvalRunStatus
from app.repositories import lease
from app.repositories.base import BaseRepository

LEASE_RENEWAL_SECONDS = lease.LEASE_RENEWAL_SECONDS
LEASE_SECONDS = lease.LEASE_SECONDS


class EvalRunRepository(BaseRepository[EvalRun]):
    """Reads and writes for eval runs."""

    model = EvalRun

    async def active_for_set(self, set_id: uuid.UUID) -> EvalRun | None:
        """The set's run that is still `running`, if any."""
        result = await self.session.execute(
            self.active_select().where(
                EvalRun.set_id == set_id, EvalRun.status == EvalRunStatus.RUNNING.value
            )
        )
        return result.scalars().first()

    async def active_for_project(self, project_id: uuid.UUID) -> EvalRun | None:
        """Any live run of the project that is still `running`, if there is one."""
        result = await self.session.execute(
            self.active_select()
            .where(EvalRun.project_id == project_id, EvalRun.status == EvalRunStatus.RUNNING.value)
            .limit(1)
        )
        return result.scalars().first()

    async def latest_for_sets(self, set_ids: Sequence[uuid.UUID]) -> dict[uuid.UUID, EvalRun]:
        """Each given set's newest run, in one query. A set with no run is absent."""
        if not set_ids:
            return {}
        result = await self.session.execute(
            self.active_select()
            .where(EvalRun.set_id.in_(set_ids))
            .order_by(EvalRun.set_id, EvalRun.created_at.desc(), EvalRun.id)
            .distinct(EvalRun.set_id)
        )
        return {run.set_id: run for run in result.scalars().all()}

    async def list_for_set(
        self, set_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[EvalRun], int]:
        """A set's runs, newest first, and the total."""
        base = self.active_select().where(EvalRun.set_id == set_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.execute(
            base.order_by(EvalRun.created_at.desc(), EvalRun.id).limit(limit).offset(offset)
        )
        return list(rows.scalars().all()), int(total or 0)

    async def claim(
        self, *, run_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take ownership of a run. True if we won it."""
        row = await lease.claim_lease(
            self.session,
            EvalRun,
            row_id=run_id,
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            extra_where=(EvalRun.status == EvalRunStatus.RUNNING.value,),
            extra_values={
                "status": EvalRunStatus.RUNNING.value,
                "started_at": func.coalesce(EvalRun.started_at, datetime.now(UTC)),
                "error": None,
            },
            returning=(EvalRun.project_id,),
        )
        if row is None:
            return False
        stage_live_event(self.session, eval_run_event(run_id, row[0]))
        return True

    async def renew_lease(self, *, run_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        return await lease.renew_lease(
            self.session,
            EvalRun,
            row_id=run_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            skip_deleted=True,
        )

    async def hold_for_commit(self, *, run_id: uuid.UUID, worker_id: str) -> bool:
        """Whether the run is still live and still ours, locking its row until commit.

        The runner asks this before each result batch commits. `deleted_at IS NULL`
        catches a project or set deleted mid-run, which `renew_lease` only notices on
        its next tick; `FOR UPDATE` makes a delete arriving now wait for the batch
        instead of slipping between the check and the commit.
        """
        result = await self.session.execute(
            select(EvalRun.id)
            .where(
                EvalRun.id == run_id,
                EvalRun.deleted_at.is_(None),
                EvalRun.lease_owner == worker_id,
            )
            .with_for_update()
        )
        return result.scalar_one_or_none() is not None

    async def release(
        self,
        *,
        run_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        status: EvalRunStatus,
        error: str | None = None,
        **fields: object,
    ) -> bool:
        """Finish a run: write the outcome and drop the lease. True if we held it."""
        row = await lease.release_lease(
            self.session,
            EvalRun,
            row_id=run_id,
            job_id=job_id,
            worker_id=worker_id,
            status=status.value,
            error=error,
            fields=fields,
            returning=(EvalRun.project_id,),
        )
        if row is None:
            return False
        stage_live_event(self.session, eval_run_event(run_id, row[0]))
        return True

    async def claim_stranded(self, *, older_than_seconds: int) -> Sequence[uuid.UUID]:
        """Take the runs that were lost, and stamp them so they stay taken.

        Same reasoning as `MockDataDatasetRepository.claim_stranded`: a run is already
        `running` before its claim, so status says nothing about whether a worker
        holds it, and stamping `updated_at` stops the sweep re-publishing it forever.
        """
        rows = await lease.claim_stranded_rows(
            self.session,
            EvalRun,
            working_status=EvalRunStatus.RUNNING.value,
            older_than_seconds=older_than_seconds,
            returning=(EvalRun.id, EvalRun.project_id),
        )
        for run_id, project_id in rows:
            stage_live_event(self.session, eval_run_event(run_id, project_id))
        return [row[0] for row in rows]

    async def defer(self, *, run_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Hand the run back for a retry due `hold_seconds` from now, still `running`.

        The lease is shortened rather than dropped, for the reason
        `MockDataDatasetRepository.defer` gives: a lease-less `running` row is what
        the sweep reads as abandoned.
        """
        row = await lease.defer_lease(
            self.session,
            EvalRun,
            row_id=run_id,
            worker_id=worker_id,
            hold_seconds=hold_seconds,
            returning=(EvalRun.project_id,),
        )
        if row is None:
            return False
        stage_live_event(self.session, eval_run_event(run_id, row[0]))
        return True

    async def soft_delete_for_set(self, set_id: uuid.UUID) -> int:
        """Soft-delete every run of a set."""
        result = await self.session.execute(
            update(EvalRun)
            .where(EvalRun.set_id == set_id, EvalRun.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every set of a project."""
        result = await self.session.execute(
            update(EvalRun)
            .where(EvalRun.project_id == project_id, EvalRun.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
