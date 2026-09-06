"""Queries over `projects`, including the claim that makes ingestion safe.

The job queue delivers at-least-once. The claim below — not the message — decides who
runs a job, so a redelivery, a consumer-group rebalance, or a duplicated publish costs
one skipped poll rather than two workers indexing the same repository.
"""

import uuid
from collections.abc import Sequence
from datetime import UTC, datetime, timedelta
from typing import Any, NamedTuple, cast

from sqlalchemy import case, func, or_, select, update
from sqlalchemy.engine import CursorResult

from app.core.access import ProjectScope
from app.models.project import Project, ProjectStatus
from app.repositories.base import BaseRepository

# How long a claim is good for. Declared beside the queries that grant and renew it so
# the consumer (which claims) and the pipeline (which renews) cannot drift apart on it
# — spec §4.2 makes five minutes safe only because renewal runs every sixty seconds.
LEASE_SECONDS = 300
LEASE_RENEWAL_SECONDS = 60


class ProjectSummary(NamedTuple):
    """The columns a checklist row needs from the project it belongs to."""

    name: str
    active_generation: int


class ProjectRepository(BaseRepository[Project]):
    """Reads and writes for projects. All reads exclude soft-deleted rows."""

    model = Project

    # `encrypted_pat` and `error` are deliberately absent: `sort` arrives from a
    # query parameter, and an unchecked column name is an information leak.
    SORTABLE_FIELDS = frozenset({"name", "status", "created_at", "updated_at"})

    async def list_page(
        self,
        *,
        scope: ProjectScope,
        page: int,
        limit: int,
        search: str | None,
        sort: str,
        descending: bool,
    ) -> tuple[Sequence[Project], int]:
        """One page of projects plus the total, restricted to `scope`.

        The scope arrives from `resolve_project_scope` and is applied here. In phase 1
        it is `unrestricted`, so no clause is added and the behaviour is identical to
        having none — which is the point: phase 2 changes the resolver's body only.
        """
        if sort not in self.SORTABLE_FIELDS:
            raise ValueError(f"unknown sort field: {sort}")

        statement = self.active_select()
        if not scope.unrestricted:
            # An empty id set means no access, not all of it — `in_(())` is false
            # for every row, which is the required fail-closed behaviour.
            statement = statement.where(Project.id.in_(scope.ids))
        if search:
            pattern = f"%{search.strip()}%"
            statement = statement.where(
                or_(Project.name.ilike(pattern), Project.repo_url.ilike(pattern))
            )

        count_result = await self.session.execute(
            select(func.count()).select_from(statement.subquery())
        )
        total = count_result.scalar_one()

        column = getattr(Project, sort)
        statement = statement.order_by(column.desc() if descending else column.asc())
        statement = statement.offset((page - 1) * limit).limit(limit)

        rows = await self.session.execute(statement)
        return rows.scalars().all(), total

    async def claim(
        self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take ownership of a project's next indexing run. True if we won it.

        Gates on two things and nothing else: no live lease, and this job has not
        already been completed.

        It cannot gate on status. A reindex leaves the project at `ready` throughout,
        so a status-based clause could never claim one. But merely permitting `ready`
        would let a redelivered message start an unwanted reindex once a finished job
        cleared its lease — `last_job_id` is what separates those two cases.
        """
        now = datetime.now(UTC)
        expires_at = now + timedelta(seconds=lease_seconds)

        statement = (
            update(Project)
            .where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
                Project.last_job_id.is_distinct_from(job_id),
                or_(Project.lease_expires_at.is_(None), Project.lease_expires_at < now),
            )
            .values(
                lease_owner=worker_id,
                lease_expires_at=expires_at,
                last_job_id=job_id,
                # One statement serves both modes: a first index moves to `cloning`,
                # a reindex stays `ready` and raises the flag instead.
                status=case(
                    (Project.status == ProjectStatus.READY.value, ProjectStatus.READY.value),
                    else_=ProjectStatus.CLONING.value,
                ),
                reindex_in_progress=case(
                    (Project.status == ProjectStatus.READY.value, True), else_=False
                ),
                # Bulk UPDATE: `onupdate` does not fire on this path
                # (.claude/rules/persistence.md).
                updated_at=now,
            )
        )
        result = await self.session.execute(statement)
        return cast(CursorResult[Any], result).rowcount == 1

    async def renew_lease(
        self, *, project_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Extend our own lease. False means we lost it and must abandon the job."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(Project)
            .where(Project.id == project_id, Project.lease_owner == worker_id)
            .values(
                lease_expires_at=now + timedelta(seconds=lease_seconds),
                updated_at=now,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def set_status(self, *, project_id: uuid.UUID, status: ProjectStatus) -> None:
        """Advance a project's status without touching its lease.

        Used mid-run, where the job still owns the project and only the state the API
        reports has moved on.
        """
        now = datetime.now(UTC)
        await self.session.execute(
            update(Project)
            .where(Project.id == project_id)
            # Bulk UPDATE: `onupdate` does not fire on this path
            # (.claude/rules/persistence.md).
            .values(status=status.value, updated_at=now)
        )

    async def release(
        self,
        *,
        project_id: uuid.UUID,
        job_id: uuid.UUID,
        worker_id: str,
        status: ProjectStatus,
        error: str | None = None,
        **fields: object,
    ) -> bool:
        """Finish a run: write the outcome and drop the lease. True if we still held it.

        `last_job_id` is set to the job just completed so a redelivery of the same
        message is recognised and skipped.

        Gated on the same two conditions as `claim`, and for the same reason — a run
        that started is not entitled to finish. Without `deleted_at IS NULL`, a
        `DELETE` landing mid-index would find `embedding_collection` still NULL
        (this statement is the only thing that writes it), skip Qdrant, and let the
        in-flight worker then write both its points and its outcome onto the
        soft-deleted row: the chunk text of a deleted repository would stay on the
        instance permanently, unreachable by any code path (`docs/PRD.md` §5.1).
        Without `lease_owner`, a worker whose lease expired and was reclaimed still
        writes its outcome, so the surviving row can name a generation the winning
        run has already deleted — a `ready` project with an empty index.

        The caller must handle `False`: the points this run wrote are unreferenced.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(Project)
            .where(
                Project.id == project_id,
                Project.deleted_at.is_(None),
                Project.lease_owner == worker_id,
            )
            .values(
                status=status.value,
                error=error,
                lease_owner=None,
                lease_expires_at=None,
                last_job_id=job_id,
                reindex_in_progress=False,
                updated_at=now,
                **fields,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def abandon(self, *, project_id: uuid.UUID, worker_id: str) -> bool:
        """Give up a run without deciding its outcome. True if we still held it.

        Expires the lease and clears `reindex_in_progress`, leaving `status`, `error`
        and `last_job_id` alone: the retry-or-dead-letter decision belongs to the
        consumer (spec §4.4), and writing `failed` here would lie about a job that is
        coming back.

        Clearing the flag is the point. `ProjectService.reindex` and `claim` are the
        only things that set it, and `release`, `abandon` and the reconcile sweep's
        re-publish the only things that resolve it, so a run ending through none of
        them — an unclassified exception — strands it at True, and
        `ProjectService.reindex` then answers `enqueued: false` forever with no route,
        flag, or admin action able to clear it.

        The lease is expired rather than cleared, so `lease_owner` still names us.
        `claim` gates on expiry alone, so the project is immediately reclaimable
        either way — but the consumer's dead-letter `release` gates on *ownership*,
        and clearing the owner here would lock it out of recording the outcome. The
        retryable path leaves the owner in place for the same reason.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(Project)
            .where(Project.id == project_id, Project.lease_owner == worker_id)
            .values(
                lease_expires_at=now,
                reindex_in_progress=False,
                # Bulk UPDATE: `onupdate` does not fire on this path
                # (.claude/rules/persistence.md).
                updated_at=now,
            )
        )
        return cast(CursorResult[Any], result).rowcount == 1

    async def find_stranded(self, *, pending_older_than_seconds: int) -> Sequence[Project]:
        """Projects whose job was lost: never picked up, or held by a dead worker.

        Three branches, one per way a job goes missing. The first covers the window
        where `POST /projects` wrote the row but the produce failed; the second covers
        a worker that died mid-run.

        The third is the reindex equivalent of the first, and it exists because
        `ProjectService.reindex` raises `reindex_in_progress` before publishing. A
        reindex leaves `status` at `ready`, so a lost produce matches neither of the
        others -- and because no worker ever claimed it, `lease_owner` is null and
        neither `release` nor `abandon` can lower the flag. Without this branch the
        project answers `enqueued: false` forever with nothing able to clear it.

        It is deliberately gated on a null lease: a run that *was* claimed carries an
        expiry and belongs to the second branch, which already re-publishes it.
        `updated_at` is the clock rather than `created_at`, because the row was created
        long before this reindex was asked for -- and `reindex` stamps it for that
        reason.
        """
        now = datetime.now(UTC)
        cutoff = now - timedelta(seconds=pending_older_than_seconds)
        statement = self.active_select().where(
            or_(
                (Project.status == ProjectStatus.PENDING.value)
                & (Project.lease_expires_at.is_(None))
                & (Project.created_at < cutoff),
                Project.lease_expires_at < now,
                Project.reindex_in_progress.is_(True)
                & (Project.lease_expires_at.is_(None))
                & (Project.updated_at < cutoff),
            )
        )
        rows = await self.session.execute(statement)
        return rows.scalars().all()

    async def names_and_generations(
        self, project_ids: Sequence[uuid.UUID]
    ) -> dict[uuid.UUID, ProjectSummary]:
        """Each project's name and `active_generation`, in one query.

        Read by the checklist module list, which needs both for every row: the name to
        render the project column, the generation to answer "is this checklist stale?".
        One statement rather than one per row, and one rather than two -- the
        alternative is an N+1 on the busiest screen in the feature.
        """
        if not project_ids:
            return {}
        result = await self.session.execute(
            select(Project.id, Project.name, Project.active_generation).where(
                Project.id.in_(project_ids), Project.deleted_at.is_(None)
            )
        )
        return {
            project_id: ProjectSummary(name=name, active_generation=generation)
            for project_id, name, generation in result.all()
        }
