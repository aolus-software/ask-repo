"""Queries over `checklist_modules`, including the lease that makes generation safe.

Every read is scoped by a `ProjectScope` the caller obtained from
`access.resolve_project_scope`, and the scope is applied here rather than in the
service so no caller can forget it -- `docs/PRD.md` 7's phase-2 criterion is that read
scoping lives in exactly one function and is confirmed by grep.

The claim is a near-copy of `ProjectRepository.claim` rather than a shared helper: the
two rows carry different status vocabularies and different outcome columns, and a
premature abstraction over them would hide the day they stop agreeing.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import Select, func, or_, select, update
from sqlalchemy.engine import CursorResult

from app.core.access import ProjectScope
from app.models.checklist import ChecklistModule, ChecklistModuleStatus
from app.repositories.base import BaseRepository

# Declared beside the queries that grant and renew it, so the consumer (which claims)
# and the generator (which renews) cannot drift apart on the number.
LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60
# How long a module may sit in `generating` with a dead lease before the sweep
# re-enqueues it.
STRANDED_AFTER_SECONDS = 120


class ChecklistModuleRepository(BaseRepository[ChecklistModule]):
    """Reads and writes for checklist modules, always inside a project scope."""

    model = ChecklistModule

    # `error`, `lease_owner` and `source_path` are deliberately absent: `sort` arrives
    # from a query parameter, and an unchecked column name is an information leak.
    SORTABLE_FIELDS = frozenset({"name", "status", "created_at", "updated_at", "last_generated_at"})

    def _scoped(
        self,
        scope: ProjectScope,
        *,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> Select[tuple[ChecklistModule]]:
        """The base query the page and the count are both built from."""
        statement = self.active_select()
        if not scope.unrestricted:
            # `in_` over an empty collection renders `WHERE false`, which is the wanted
            # behaviour: an empty scope means no access, never all of it.
            statement = statement.where(ChecklistModule.project_id.in_(scope.ids))
        if project_id is not None:
            # A filter *within* the scope, not the scope itself.
            statement = statement.where(ChecklistModule.project_id == project_id)
        if status:
            statement = statement.where(ChecklistModule.status == status)
        if search:
            term = f"%{search.strip()}%"
            statement = statement.where(
                ChecklistModule.name.ilike(term) | ChecklistModule.source_path.ilike(term)
            )
        return statement

    async def list_page(
        self,
        *,
        scope: ProjectScope,
        page: int,
        limit: int,
        sort: str,
        descending: bool,
        project_id: uuid.UUID | None = None,
        status: str | None = None,
        search: str | None = None,
    ) -> tuple[list[ChecklistModule], int]:
        """One page of modules, plus the unpaginated total for the same filters."""
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"cannot sort checklist modules by {sort!r}")

        base = self._scoped(scope, project_id=project_id, status=status, search=search)
        column = getattr(ChecklistModule, sort)
        # `id` breaks ties so a page boundary is stable across requests.
        rows = await self.session.execute(
            base.order_by(column.desc() if descending else column.asc(), ChecklistModule.id.asc())
            .offset((page - 1) * limit)
            .limit(limit)
        )
        total = await self.session.execute(select(func.count()).select_from(base.subquery()))
        return list(rows.scalars().all()), total.scalar_one()

    async def get_in_scope(
        self, module_id: uuid.UUID, *, scope: ProjectScope
    ) -> ChecklistModule | None:
        """One module, if it is in the caller's scope. `None` means 404."""
        result = await self.session.execute(
            self._scoped(scope).where(ChecklistModule.id == module_id)
        )
        return result.scalar_one_or_none()

    async def claim(
        self, *, module_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take ownership of a module's next generation. True if we won it.

        Gates on two things: no live lease, and this job has not already been
        completed. The second is what separates a redelivery of a finished job from a
        fresh request -- without it, a redelivered message starts an unwanted second
        generation the moment the first cleared its lease.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(ChecklistModule)
            .where(
                ChecklistModule.id == module_id,
                ChecklistModule.deleted_at.is_(None),
                ChecklistModule.last_job_id.is_distinct_from(job_id),
                or_(
                    ChecklistModule.lease_expires_at.is_(None),
                    ChecklistModule.lease_expires_at < now,
                ),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                last_job_id=job_id,
                status=ChecklistModuleStatus.GENERATING.value,
                error=None,
                # Bulk UPDATE: `onupdate` does not fire on this path
                # (.claude/rules/persistence.md).
                updated_at=now,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def renew_lease(
        self, *, module_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(ChecklistModule)
            .where(ChecklistModule.id == module_id, ChecklistModule.lease_owner == worker_id)
            .values(lease_expires_at=now + timedelta(seconds=lease_seconds), updated_at=now)
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def release(
        self,
        *,
        module_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        status: ChecklistModuleStatus,
        error: str | None = None,
        **fields: object,
    ) -> bool:
        """Finish a run: write the outcome and drop the lease. True if we still held it.

        Guarded on the same conditions the claim was granted under. Without
        `deleted_at IS NULL` a module deleted mid-generation is written back to life;
        without `lease_owner` a worker whose lease expired overwrites the winner's
        outcome. The `rowcount` is a return value, never discarded: `False` means this
        run lost the right to record itself.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(ChecklistModule)
            .where(
                ChecklistModule.id == module_id,
                ChecklistModule.deleted_at.is_(None),
                ChecklistModule.lease_owner == worker_id,
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

    async def mark_in_review(self, module_id: uuid.UUID) -> None:
        """Move a module to `review` because a proposal is now pending.

        A bulk UPDATE from the stream's own session, so `updated_at` is set explicitly
        (`.claude/rules/persistence.md`).
        """
        await self.session.execute(
            update(ChecklistModule)
            .where(ChecklistModule.id == module_id, ChecklistModule.deleted_at.is_(None))
            .values(status=ChecklistModuleStatus.REVIEW.value, updated_at=func.now())
        )

    async def find_stranded(
        self, *, generating_older_than_seconds: int
    ) -> Sequence[ChecklistModule]:
        """Modules whose generation was lost: the produce failed, or a worker died.

        Two gaps the queue cannot close on its own, matching
        `ProjectRepository.find_stranded`. Safe to run on every worker concurrently --
        the claim deduplicates, so a duplicate message costs one skipped poll.
        """
        cutoff = datetime.now(UTC) - timedelta(seconds=generating_older_than_seconds)
        now = datetime.now(UTC)
        result = await self.session.execute(
            self.active_select().where(
                ChecklistModule.status == ChecklistModuleStatus.GENERATING.value,
                ChecklistModule.updated_at < cutoff,
                or_(
                    ChecklistModule.lease_expires_at.is_(None),
                    ChecklistModule.lease_expires_at < now,
                ),
            )
        )
        return result.scalars().all()

    async def soft_delete_for_project(self, project_id: uuid.UUID) -> int:
        """Soft-delete every module of a project, for every creator.

        `updated_at` is set explicitly and from the database clock: `onupdate` does not
        fire on a bulk UPDATE, and mixing Python's clock with the server default used
        everywhere else lets an update land before the `created_at` it updates.
        """
        result = await self.session.execute(
            update(ChecklistModule)
            .where(
                ChecklistModule.project_id == project_id,
                ChecklistModule.deleted_at.is_(None),
            )
            .values(deleted_at=func.now(), updated_at=func.now())
        )
        return cast(CursorResult[Any], result).rowcount
