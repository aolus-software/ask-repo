"""Queries over `mock_data_datasets`, including the generation lease.

A near-copy of `ChecklistModuleRepository`'s lease logic rather than a shared helper --
the two rows carry independent status vocabularies and outcome columns, and a premature
abstraction over them would hide the day they stop agreeing (same reasoning that
repository's own docstring gives for not sharing with `ProjectRepository.claim`).

Unscoped by `ProjectScope`, like `ChecklistChangeSetRepository`: a dataset is always
reached through its module, and the module read is already scoped.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import func, or_, select, update
from sqlalchemy.engine import CursorResult

from app.models.checklist import ChecklistModule
from app.models.mock_data import MockDataDataset, MockDataDatasetStatus
from app.repositories.base import BaseRepository

LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60
STRANDED_AFTER_SECONDS = 120


class MockDataDatasetRepository(BaseRepository[MockDataDataset]):
    """Reads and writes for a module's mock-data dataset row."""

    model = MockDataDataset

    async def get_by_module(self, module_id: uuid.UUID) -> MockDataDataset | None:
        """The dataset row for a module, if one has ever been generated."""
        result = await self.session.execute(
            self.active_select().where(MockDataDataset.checklist_module_id == module_id)
        )
        return result.scalar_one_or_none()

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
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.id == dataset_id,
                MockDataDataset.deleted_at.is_(None),
                MockDataDataset.last_job_id.is_distinct_from(job_id),
                or_(
                    MockDataDataset.lease_expires_at.is_(None),
                    MockDataDataset.lease_expires_at < now,
                ),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                last_job_id=job_id,
                status=MockDataDatasetStatus.GENERATING.value,
                error=None,
                updated_at=now,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def renew_lease(
        self, *, dataset_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(MockDataDataset)
            .where(MockDataDataset.id == dataset_id, MockDataDataset.lease_owner == worker_id)
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
        )
        return cast(CursorResult[Any], result).rowcount == 1

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
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.id == dataset_id,
                MockDataDataset.deleted_at.is_(None),
                MockDataDataset.lease_owner == worker_id,
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
        )
        return cast(CursorResult[Any], result).rowcount == 1

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
        await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.id == dataset_id,
                MockDataDataset.deleted_at.is_(None),
                MockDataDataset.status != MockDataDatasetStatus.GENERATING.value,
            )
            .values(status=MockDataDatasetStatus.REVIEW.value, updated_at=func.now())
        )

    async def claim_stranded(self, *, generating_older_than_seconds: int) -> Sequence[uuid.UUID]:
        """Take the datasets whose generation was lost, and stamp them so they stay taken.

        Same reasoning as `ChecklistModuleRepository.claim_stranded`: a dataset is
        already `generating` before its claim and stays `generating` throughout, so
        status alone says nothing about whether a worker holds it. Stamping
        `updated_at` is what stops the sweep re-publishing the same dataset forever.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=generating_older_than_seconds)
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.deleted_at.is_(None),
                MockDataDataset.status == MockDataDatasetStatus.GENERATING.value,
                MockDataDataset.updated_at < cutoff,
                or_(
                    MockDataDataset.lease_expires_at.is_(None),
                    MockDataDataset.lease_expires_at < now,
                ),
            )
            .values(updated_at=now)
            .returning(MockDataDataset.id)
        )
        return list(result.scalars().all())

    async def defer(self, *, dataset_id: uuid.UUID, worker_id: str) -> bool:
        """Drop our lease but leave the dataset `generating`. True if we still held it."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(MockDataDataset)
            .where(
                MockDataDataset.id == dataset_id,
                MockDataDataset.deleted_at.is_(None),
                MockDataDataset.lease_owner == worker_id,
            )
            .values(lease_owner=None, lease_expires_at=None, updated_at=now)
        )
        return cast(CursorResult[Any], result).rowcount == 1

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
