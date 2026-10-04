"""Queries over `eval_sets`, including the generation lease.

A near-copy of `MockDataDatasetRepository`'s lease logic, for the reasons that
repository's docstring gives. Unscoped by `ProjectScope`: access is decided in
`app/core/access.py`, and these methods filter only by ids they are handed.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult

from app.live.events import eval_run_event
from app.live.staging import stage_live_event
from app.models.eval import EvalRun, EvalRunStatus
from app.repositories.base import BaseRepository

LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60
STRANDED_AFTER_SECONDS = 120


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
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalRun)
            .where(
                EvalRun.id == run_id,
                EvalRun.deleted_at.is_(None),
                EvalRun.last_job_id.is_distinct_from(job_id),
                or_(EvalRun.lease_expires_at.is_(None), EvalRun.lease_expires_at < now),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                last_job_id=job_id,
                status=EvalRunStatus.RUNNING.value,
                started_at=now,
                error=None,
                updated_at=now,
            )
            .returning(EvalRun.project_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        stage_live_event(self.session, eval_run_event(run_id, row[0]))
        return True

    async def renew_lease(self, *, run_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalRun)
            .where(EvalRun.id == run_id, EvalRun.lease_owner == worker_id)
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
        )
        return cast(CursorResult[Any], result).rowcount == 1

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
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalRun)
            .where(
                EvalRun.id == run_id,
                EvalRun.deleted_at.is_(None),
                EvalRun.lease_owner == worker_id,
            )
            .values(
                status=status.value,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                last_job_id=job_id,
                updated_at=now,
                **fields,
            )
            .returning(EvalRun.project_id)
        )
        row = result.one_or_none()
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
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=older_than_seconds)
        result = await self.session.execute(
            update(EvalRun)
            .where(
                EvalRun.deleted_at.is_(None),
                EvalRun.status == EvalRunStatus.RUNNING.value,
                EvalRun.updated_at < cutoff,
                or_(EvalRun.lease_expires_at.is_(None), EvalRun.lease_expires_at < now),
            )
            .values(updated_at=now)
            .returning(EvalRun.id, EvalRun.project_id)
        )
        rows = result.all()
        for run_id, project_id in rows:
            stage_live_event(self.session, eval_run_event(run_id, project_id))
        return [row[0] for row in rows]

    async def defer(self, *, run_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Hand the run back for a retry due `hold_seconds` from now, still `running`.

        The lease is shortened rather than dropped, for the reason
        `MockDataDatasetRepository.defer` gives: a lease-less `running` row is what
        the sweep reads as abandoned.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalRun)
            .where(
                EvalRun.id == run_id,
                EvalRun.deleted_at.is_(None),
                EvalRun.lease_owner == worker_id,
            )
            .values(lease_expires_at=now + timedelta(seconds=hold_seconds), updated_at=now)
            .returning(EvalRun.project_id)
        )
        row = result.one_or_none()
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
