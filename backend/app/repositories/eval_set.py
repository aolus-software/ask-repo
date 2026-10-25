"""Queries over `eval_sets`, including the generation lease.

The lease statements are the shared ones in `app/repositories/lease.py`; each method
here passes this table's status vocabulary and stages its own live event. Unscoped by `ProjectScope`: access is decided in
`app/core/access.py`, and these methods filter only by ids they are handed.
"""

import uuid
from collections.abc import Sequence
from typing import Any, cast

from sqlalchemy import func, select, update
from sqlalchemy.engine import CursorResult

from app.live.events import eval_set_event
from app.live.staging import stage_live_event
from app.models.eval import EvalSet, EvalSetStatus
from app.repositories import lease
from app.repositories.base import BaseRepository

LEASE_RENEWAL_SECONDS = lease.LEASE_RENEWAL_SECONDS
LEASE_SECONDS = lease.LEASE_SECONDS


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

    async def live_translation(self, source_set_id: uuid.UUID, language: str) -> EvalSet | None:
        """The source's live translation into `language`, if one exists."""
        result = await self.session.execute(
            self.active_select().where(
                EvalSet.source_set_id == source_set_id, EvalSet.language == language
            )
        )
        return result.scalars().first()

    async def generating_translation_of(self, source_set_id: uuid.UUID) -> EvalSet | None:
        """A live translation of the source whose own generation is still running, if any."""
        result = await self.session.execute(
            self.active_select()
            .where(
                EvalSet.source_set_id == source_set_id,
                EvalSet.status == EvalSetStatus.GENERATING.value,
            )
            .limit(1)
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
        row = await lease.claim_lease(
            self.session,
            EvalSet,
            row_id=set_id,
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            # A sweep-published copy carries a fresh job id, so `last_job_id` cannot
            # refuse it; a finished row must refuse on status instead.
            extra_where=(EvalSet.status == EvalSetStatus.GENERATING.value,),
            extra_values={"status": EvalSetStatus.GENERATING.value, "error": None},
            returning=(EvalSet.project_id,),
        )
        if row is None:
            return False
        stage_live_event(self.session, eval_set_event(set_id, row[0]))
        return True

    async def renew_lease(self, *, set_id: uuid.UUID, worker_id: str, lease_seconds: int) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        return await lease.renew_lease(
            self.session,
            EvalSet,
            row_id=set_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            skip_deleted=True,
        )

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
        row = await lease.release_lease(
            self.session,
            EvalSet,
            row_id=set_id,
            job_id=job_id,
            worker_id=worker_id,
            status=status.value,
            error=error,
            fields=fields,
            returning=(EvalSet.project_id,),
        )
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
        rows = await lease.claim_stranded_rows(
            self.session,
            EvalSet,
            working_status=EvalSetStatus.GENERATING.value,
            older_than_seconds=older_than_seconds,
            returning=(EvalSet.id, EvalSet.project_id),
        )
        for set_id, project_id in rows:
            stage_live_event(self.session, eval_set_event(set_id, project_id))
        return [row[0] for row in rows]

    async def defer(self, *, set_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Hand the set back for a retry due `hold_seconds` from now, still `generating`.

        The lease is shortened rather than dropped, for the reason
        `MockDataDatasetRepository.defer` gives: a lease-less `generating` row is what
        the sweep reads as abandoned.
        """
        row = await lease.defer_lease(
            self.session,
            EvalSet,
            row_id=set_id,
            worker_id=worker_id,
            hold_seconds=hold_seconds,
            returning=(EvalSet.project_id,),
        )
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
