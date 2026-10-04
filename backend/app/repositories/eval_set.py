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

from app.live.events import eval_set_event
from app.live.staging import stage_live_event
from app.models.eval import EvalSet, EvalSetStatus
from app.repositories.base import BaseRepository

LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60
STRANDED_AFTER_SECONDS = 120


class EvalSetRepository(BaseRepository[EvalSet]):
    """Reads and writes for eval sets."""

    model = EvalSet

    async def lock(self, set_id: uuid.UUID) -> EvalSet | None:
        """The set's row, locked `FOR UPDATE` until the transaction ends.

        Serialises concurrent run requests: `eval_runs` has no unique index that could
        refuse a second `running` row, so the second request waits here and then sees
        the first's run in `active_for_set`. `populate_existing` refreshes a row the
        session already holds, so the status read after the lock is the committed one.
        """
        result = await self.session.execute(
            self.active_select()
            .where(EvalSet.id == set_id)
            .with_for_update()
            .execution_options(populate_existing=True)
        )
        return result.scalars().first()

    async def list_for_project(
        self, project_id: uuid.UUID, *, limit: int, offset: int
    ) -> tuple[list[EvalSet], int]:
        """A project's sets, newest first, and the total."""
        base = self.active_select().where(EvalSet.project_id == project_id)
        total = await self.session.scalar(select(func.count()).select_from(base.subquery()))
        rows = await self.session.execute(
            base.order_by(EvalSet.created_at.desc(), EvalSet.id).limit(limit).offset(offset)
        )
        return list(rows.scalars().all()), int(total or 0)

    async def claim(
        self, *, set_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take ownership of a set's generation. True if we won it."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalSet)
            .where(
                EvalSet.id == set_id,
                EvalSet.deleted_at.is_(None),
                # A sweep-published copy carries a fresh job id, so `last_job_id` cannot
                # refuse it; a finished row must refuse on status instead.
                EvalSet.status == EvalSetStatus.GENERATING.value,
                EvalSet.last_job_id.is_distinct_from(job_id),
                or_(EvalSet.lease_expires_at.is_(None), EvalSet.lease_expires_at < now),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                last_job_id=job_id,
                status=EvalSetStatus.GENERATING.value,
                error=None,
                updated_at=now,
            )
            .returning(EvalSet.project_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        stage_live_event(self.session, eval_set_event(set_id, row[0]))
        return True

    async def renew_lease(self, *, set_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalSet)
            .where(
                EvalSet.id == set_id,
                EvalSet.deleted_at.is_(None),
                EvalSet.lease_owner == worker_id,
            )
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def release(
        self,
        *,
        set_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        status: EvalSetStatus,
        error: str | None = None,
        **fields: object,
    ) -> bool:
        """Finish a generation: write the outcome and drop the lease. True if we held it."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalSet)
            .where(
                EvalSet.id == set_id,
                EvalSet.deleted_at.is_(None),
                EvalSet.lease_owner == worker_id,
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
            .returning(EvalSet.project_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        stage_live_event(self.session, eval_set_event(set_id, row[0]))
        return True

    async def claim_stranded(self, *, older_than_seconds: int) -> Sequence[uuid.UUID]:
        """Take the sets whose generation was lost, and stamp them so they stay taken.

        Same reasoning as `MockDataDatasetRepository.claim_stranded`: a set is already
        `generating` before its claim, so status says nothing about whether a worker
        holds it, and stamping `updated_at` stops the sweep re-publishing it forever.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=older_than_seconds)
        result = await self.session.execute(
            update(EvalSet)
            .where(
                EvalSet.deleted_at.is_(None),
                EvalSet.status == EvalSetStatus.GENERATING.value,
                EvalSet.updated_at < cutoff,
                or_(EvalSet.lease_expires_at.is_(None), EvalSet.lease_expires_at < now),
            )
            .values(updated_at=now)
            .returning(EvalSet.id, EvalSet.project_id)
        )
        rows = result.all()
        for set_id, project_id in rows:
            stage_live_event(self.session, eval_set_event(set_id, project_id))
        return [row[0] for row in rows]

    async def defer(self, *, set_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Hand the set back for a retry due `hold_seconds` from now, still `generating`.

        The lease is shortened rather than dropped, for the reason
        `MockDataDatasetRepository.defer` gives: a lease-less `generating` row is what
        the sweep reads as abandoned.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(EvalSet)
            .where(
                EvalSet.id == set_id,
                EvalSet.deleted_at.is_(None),
                EvalSet.lease_owner == worker_id,
            )
            .values(lease_expires_at=now + timedelta(seconds=hold_seconds), updated_at=now)
            .returning(EvalSet.project_id)
        )
        row = result.one_or_none()
        if row is None:
            return False
        stage_live_event(self.session, eval_set_event(set_id, row[0]))
        return True

    async def soft_delete_set(self, set_id: uuid.UUID, project_id: uuid.UUID) -> None:
        """Soft-delete one set and stage its live event."""
        await self.session.execute(
            update(EvalSet)
            .where(EvalSet.id == set_id, EvalSet.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        stage_live_event(self.session, eval_set_event(set_id, project_id))

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every set of a project."""
        result = await self.session.execute(
            update(EvalSet)
            .where(EvalSet.project_id == project_id, EvalSet.deleted_at.is_(None))
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
