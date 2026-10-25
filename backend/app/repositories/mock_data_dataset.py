"""Queries over `mock_data_datasets`, including the generation lease.

The lease statements are the shared ones in `app/repositories/lease.py`; each method here
passes this table's status vocabulary and outcome columns and stages its own live event.

Unscoped by `ProjectScope`, like `ChecklistChangeSetRepository`: a dataset is always
reached through its module, and the module read is already scoped.
"""

import uuid
from collections.abc import Collection, Sequence
from typing import Any, cast

from sqlalchemy import ScalarSelect, func, select, update
from sqlalchemy.engine import CursorResult

from app.live.events import mock_data_event
from app.live.staging import stage_live_event
from app.models.checklist import ChecklistModule
from app.models.mock_data import MockDataDataset, MockDataDatasetStatus
from app.repositories import lease
from app.repositories.base import BaseRepository

LEASE_RENEWAL_SECONDS = lease.LEASE_RENEWAL_SECONDS
LEASE_SECONDS = lease.LEASE_SECONDS


def _dataset_project_id() -> ScalarSelect[uuid.UUID]:
    """The dataset's project, reached through its module (datasets carry no project_id)."""
    return (
        select(ChecklistModule.project_id)
        .where(ChecklistModule.id == MockDataDataset.checklist_module_id)
        .scalar_subquery()
    )


class MockDataDatasetRepository(BaseRepository[MockDataDataset]):
    """Reads and writes for a module's mock-data dataset row."""

    model = MockDataDataset

    async def get_by_module(self, module_id: uuid.UUID) -> MockDataDataset | None:
        """The dataset row for a module, if one has ever been generated."""
        result = await self.session.execute(
            self.active_select().where(MockDataDataset.checklist_module_id == module_id)
        )
        return result.scalar_one_or_none()

    async def get_by_modules(
        self, module_ids: Collection[uuid.UUID]
    ) -> dict[uuid.UUID, MockDataDataset]:
        """The dataset rows of several modules, keyed by module. A missing key means none."""
        if not module_ids:
            return {}
        result = await self.session.execute(
            self.active_select().where(MockDataDataset.checklist_module_id.in_(module_ids))
        )
        return {row.checklist_module_id: row for row in result.scalars().all()}

    async def get_or_create_for_module(self, module_id: uuid.UUID) -> MockDataDataset:
        """The dataset row for a module, creating an empty one on first use.

        A module can carry a checklist, a mock dataset, both, or neither -- so there is
        no dataset row until the first generation is requested against this module.
        """
        existing = await self.get_by_module(module_id)
        if existing is not None:
            return existing
        return await self.add(
            MockDataDataset(
                id=uuid.uuid4(),
                checklist_module_id=module_id,
                status=MockDataDatasetStatus.EMPTY.value,
            )
        )

    async def claim(
        self, *, dataset_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take ownership of a dataset's next generation. True if we won it."""
        row = await lease.claim_lease(
            self.session,
            MockDataDataset,
            row_id=dataset_id,
            job_id=job_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            extra_values={"status": MockDataDatasetStatus.GENERATING.value, "error": None},
            returning=(MockDataDataset.checklist_module_id, _dataset_project_id()),
        )
        if row is None:
            return False
        module_id, project_id = row
        stage_live_event(self.session, mock_data_event(module_id, project_id))
        return True

    async def renew_lease(
        self, *, dataset_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        return await lease.renew_lease(
            self.session,
            MockDataDataset,
            row_id=dataset_id,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            skip_deleted=False,
        )

    async def release(
        self,
        *,
        dataset_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        status: MockDataDatasetStatus,
        error: str | None = None,
        **fields: object,
    ) -> bool:
        """Finish a run: write the outcome and drop the lease. True if we still held it."""
        row = await lease.release_lease(
            self.session,
            MockDataDataset,
            row_id=dataset_id,
            job_id=job_id,
            worker_id=worker_id,
            status=status.value,
            error=error,
            fields=fields,
            returning=(MockDataDataset.checklist_module_id, _dataset_project_id()),
        )
        if row is None:
            return False
        module_id, project_id = row
        stage_live_event(self.session, mock_data_event(module_id, project_id))
        return True

    async def mark_in_review(self, dataset_id: uuid.UUID) -> None:
        """Move a dataset to `review` because a proposal is now pending.

        Guarded on the current status not being `generating`: a live worker holds
        that dataset's lease, and `MockDataDatasetService.prepare_turn` is supposed to
        refuse the chat turn before this is ever called for such a row. This predicate
        makes the clobber structurally impossible rather than merely unreachable --
        writing `review` over a `generating` row would blind the reconcile sweep (which
        has no other signal that a worker still holds the lease) and, if the worker
        finished normally instead, would leave a second pending change set behind it.
        """
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.id == dataset_id,
                MockDataDataset.deleted_at.is_(None),
                MockDataDataset.status != MockDataDatasetStatus.GENERATING.value,
            )
            .values(status=MockDataDatasetStatus.REVIEW.value, updated_at=func.now())
            .returning(MockDataDataset.checklist_module_id, _dataset_project_id())
        )
        row = result.one_or_none()
        if row is not None:
            module_id, project_id = row
            stage_live_event(self.session, mock_data_event(module_id, project_id))

    async def claim_stranded(self, *, generating_older_than_seconds: int) -> Sequence[uuid.UUID]:
        """Take the datasets whose generation was lost, and stamp them so they stay taken.

        Same reasoning as `ChecklistModuleRepository.claim_stranded`: a dataset is
        already `generating` before its claim and stays `generating` throughout, so
        status alone says nothing about whether a worker holds it. Stamping
        `updated_at` is what stops the sweep re-publishing the same dataset forever.
        """
        rows = await lease.claim_stranded_rows(
            self.session,
            MockDataDataset,
            working_status=MockDataDatasetStatus.GENERATING.value,
            older_than_seconds=generating_older_than_seconds,
            returning=(
                MockDataDataset.id,
                MockDataDataset.checklist_module_id,
                _dataset_project_id(),
            ),
        )
        for _, module_id, project_id in rows:
            stage_live_event(self.session, mock_data_event(module_id, project_id))
        return [row[0] for row in rows]

    async def defer(self, *, dataset_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Hand the dataset back for a retry due `hold_seconds` from now, still
        `generating`. True if we still held the lease.

        The lease is shortened to the retry's due moment rather than dropped, for the
        reason `ChecklistModuleRepository.defer` sets out at length: a `generating` row
        with no lease is what the reconcile sweep reads as abandoned, so a long rung
        would have it published a second time while the first retry is still pending.
        """
        row = await lease.defer_lease(
            self.session,
            MockDataDataset,
            row_id=dataset_id,
            worker_id=worker_id,
            hold_seconds=hold_seconds,
            returning=(MockDataDataset.checklist_module_id, _dataset_project_id()),
        )
        if row is None:
            return False
        module_id, project_id = row
        stage_live_event(self.session, mock_data_event(module_id, project_id))
        return True

    async def soft_delete_for_module(self, module_id: uuid.UUID) -> int:
        """Soft-delete a module's dataset row, if it has one."""
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.checklist_module_id == module_id,
                MockDataDataset.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every dataset row of every module of a project."""
        modules = select(ChecklistModule.id).where(ChecklistModule.project_id == project_id)
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.checklist_module_id.in_(modules),
                MockDataDataset.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
