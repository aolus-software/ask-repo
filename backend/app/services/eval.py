"""Eval set business rules: the generation request, reads, delete, and excluding a pair.

Every method decides access through `app/core/access.py` -- `require_readable_project`
for "may this caller know the project exists" and `require_permission` for what they
may do to it. A set has no scope of its own: it inherits its project's, so a set id
resolves to its project first and a caller with no membership there gets
`PROJECT_NOT_FOUND`, never a hint that the set exists.
"""

import time
import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.core.permissions import Permission
from app.live.events import eval_run_event, eval_set_event
from app.live.staging import stage_live_event
from app.models.eval import EvalPair, EvalResult, EvalRun, EvalRunStatus, EvalSet, EvalSetStatus
from app.models.project import Project
from app.queue.protocol import EvalQueue
from app.queue.topics import EvalJobMessage
from app.repositories.eval_pair import EvalPairRepository
from app.repositories.eval_result import EvalResultRepository
from app.repositories.eval_run import EvalRunRepository
from app.repositories.eval_set import EvalSetRepository
from app.repositories.project import ProjectRepository
from app.schemas.eval import (
    EvalPairExclude,
    EvalPairRead,
    EvalResultRead,
    EvalRunDetail,
    EvalRunSummary,
    EvalSetCreate,
    EvalSetDetail,
    EvalSetSummary,
)
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.services.index_guards import require_indexed, require_path_indexed, require_stable_index
from app.services.indexed_path import IndexedPathReader


class EvalService:
    """Eval set reads, the generation trigger, delete, and pair exclusion."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        indexed_paths: IndexedPathReader,
        recorder: AuditRecorder,
    ) -> None:
        self.session = session
        self.settings = settings
        self.indexed_paths = indexed_paths
        self._recorder = recorder
        self.sets = EvalSetRepository(session)
        self.pairs = EvalPairRepository(session)
        self.runs = EvalRunRepository(session)
        self.results = EvalResultRepository(session)
        self.projects = ProjectRepository(session)

    async def create_set(
        self,
        project_id: uuid.UUID,
        payload: EvalSetCreate,
        *,
        actor: AuthenticatedUser,
        queue: EvalQueue,
    ) -> EvalSetSummary:
        """Write a `generating` set, publish its job, audit after the commit."""
        project = await access.require_readable_project(self.projects, project_id, actor)
        access.require_permission(actor, project.id, Permission.EVAL_RUN)
        require_indexed(project)
        require_stable_index(project)
        if payload.source_path:
            await require_path_indexed(self.indexed_paths, project, payload.source_path)

        eval_set = await self.sets.add(
            EvalSet(
                id=uuid.uuid4(),
                project_id=project.id,
                name=payload.name.strip(),
                source_path=payload.source_path or None,
                requested_count=payload.count,
                mix=payload.mix.value,
                status=EvalSetStatus.GENERATING.value,
                pair_count=0,
                created_by=actor.id,
            )
        )
        stage_live_event(self.session, eval_set_event(eval_set.id, project.id))
        # Captured before the commit expires the row.
        summary = self._summary(eval_set, latest_run=None)
        name, source_path = eval_set.name, eval_set.source_path
        requested_count, mix = eval_set.requested_count, eval_set.mix
        set_id = eval_set.id
        await self.session.commit()

        await queue.enqueue_eval(
            EvalJobMessage(
                kind="generate",
                target_id=set_id,
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=int(time.time() * 1000),
                original_topic=self.settings.kafka_eval_topic,
            )
        )
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.EVAL_SET_GENERATION_REQUESTED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="eval_set",
                target_id=set_id,
                target_label=name,
                project_id=project.id,
                changed={
                    "name": (None, name),
                    "sourcePath": (None, source_path),
                    "requestedCount": (None, requested_count),
                    "mix": (None, mix),
                },
            )
        )
        return summary

    async def list_sets(
        self, project_id: uuid.UUID, query: ListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[EvalSetSummary]:
        """A page of a project's sets, each with its newest run."""
        project = await access.require_readable_project(self.projects, project_id, actor)
        access.require_permission(actor, project.id, Permission.EVAL_READ)
        rows, total = await self.sets.list_for_project(
            project.id, limit=query.limit, offset=(query.page - 1) * query.limit
        )
        latest = await self.runs.latest_for_sets([row.id for row in rows])
        return PaginatedResponse.build(
            [self._summary(row, latest_run=latest.get(row.id)) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get_set(self, set_id: uuid.UUID, *, actor: AuthenticatedUser) -> EvalSetDetail:
        """One set with every pair, excluded ones flagged."""
        eval_set, project = await self._load_set(set_id, actor, Permission.EVAL_READ)
        pairs = await self.pairs.list_for_set(eval_set.id, include_excluded=True)
        latest = await self.runs.latest_for_sets([eval_set.id])
        summary = self._summary(eval_set, latest_run=latest.get(eval_set.id))
        return EvalSetDetail(
            **summary.model_dump(),
            pairs=[self._pair(pair) for pair in pairs],
            project_generation=project.active_generation,
        )

    async def delete_set(self, set_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete a set and everything beneath it, in one transaction."""
        eval_set, project = await self._load_set(set_id, actor, Permission.EVAL_RUN)
        # The same lock `start_run` takes: the guard below is check-then-delete.
        if await self.sets.lock(set_id) is None:
            raise self._set_not_found()
        if await self.runs.active_for_set(eval_set.id) is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EVAL_RUN_IN_PROGRESS,
                "A run is in progress for this set. Wait for it to finish before deleting.",
            )
        name, source_path, pair_count = eval_set.name, eval_set.source_path, eval_set.pair_count
        _, run_count = await self.runs.list_for_set(eval_set.id, limit=1, offset=0)
        project_id = project.id

        await self.results.soft_delete_for_runs_of_set(set_id)
        await self.runs.soft_delete_for_set(set_id)
        await self.pairs.soft_delete_for_set(set_id)
        await self.sets.soft_delete_set(set_id, project_id)
        await self.session.commit()

        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.EVAL_SET_DELETED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="eval_set",
                target_id=set_id,
                target_label=name,
                project_id=project_id,
                changed={"name": (name, None), "sourcePath": (source_path, None)},
                context={"pairCount": pair_count, "runCount": run_count},
            )
        )

    async def set_excluded(
        self, pair_id: uuid.UUID, payload: EvalPairExclude, *, actor: AuthenticatedUser
    ) -> EvalPairRead:
        """Take a pair out of future runs, or put it back. A no-op writes nothing."""
        pair = await self.pairs.get(pair_id)
        if pair is None:
            raise self._set_not_found()
        eval_set, project = await self._load_set(pair.set_id, actor, Permission.EVAL_RUN)
        before = pair.excluded_at is not None
        if before == payload.excluded:
            return self._pair(pair)

        now = datetime.now(UTC)
        pair.excluded_at = now if payload.excluded else None
        pair.updated_at = now
        stage_live_event(self.session, eval_set_event(eval_set.id, project.id))
        set_name, project_id = eval_set.name, project.id
        await self.session.commit()
        read = self._pair(pair)

        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.EVAL_PAIR_UPDATED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="eval_pair",
                target_id=pair_id,
                target_label=set_name,
                project_id=project_id,
                changed={"excluded": (before, payload.excluded)},
            )
        )
        return read

    async def start_run(
        self, set_id: uuid.UUID, *, actor: AuthenticatedUser, queue: EvalQueue
    ) -> EvalRunSummary:
        """Write a `running` run, publish its job, audit after the commit.

        There is no `pending` state: the row is `running` from the request, and the
        worker's lease says whether anyone holds it.
        """
        eval_set, project = await self._load_set(set_id, actor, Permission.EVAL_RUN)
        # Serialise against `ProjectService.reindex`, which refuses while a run is
        # `running`: whichever takes the project row second sees the other's write.
        # Lock order is project then set — the order project deletion takes them in
        # (its soft delete updates the project row, then the set rows) — so no cycle.
        locked_project = await self.projects.lock(project.id)
        if locked_project is None:
            raise self._set_not_found()
        project = locked_project
        # Serialise concurrent starts on the set row; the guard below is check-then-insert.
        locked = await self.sets.lock(set_id)
        if locked is None:
            raise self._set_not_found()
        eval_set = locked
        if eval_set.status != EvalSetStatus.READY.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EVAL_SET_NOT_READY,
                "This eval set has not finished generating.",
            )
        if await self.runs.active_for_set(set_id) is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EVAL_RUN_IN_PROGRESS,
                "A run of this set is already in progress.",
            )
        access.require_answerable(project, self.settings)
        require_stable_index(project)
        included = await self.pairs.list_for_set(set_id, include_excluded=False)
        if not included:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EVAL_SET_NOT_READY,
                "Every pair in this set is excluded.",
            )

        run = await self.runs.add(
            EvalRun(
                id=uuid.uuid4(),
                set_id=set_id,
                project_id=project.id,
                status=EvalRunStatus.RUNNING.value,
                created_by=actor.id,
            )
        )
        stage_live_event(self.session, eval_run_event(run.id, project.id))
        run_id, project_id = run.id, project.id
        set_name, pair_count = eval_set.name, len(included)
        await self.session.commit()
        await self.session.refresh(run)
        summary = EvalRunSummary.model_validate(run)

        await queue.enqueue_eval(
            EvalJobMessage(
                kind="run",
                target_id=run_id,
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=int(time.time() * 1000),
                original_topic=self.settings.kafka_eval_topic,
            )
        )
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.EVAL_RUN_REQUESTED,
                actor_user_id=actor.id,
                actor_email=actor.email,
                target_type="eval_run",
                target_id=run_id,
                target_label=set_name,
                project_id=project_id,
                context={"pairCount": pair_count},
            )
        )
        return summary

    async def list_runs(
        self, set_id: uuid.UUID, query: ListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[EvalRunSummary]:
        """A page of a set's runs, newest first."""
        eval_set, _ = await self._load_set(set_id, actor, Permission.EVAL_READ)
        rows, total = await self.runs.list_for_set(
            eval_set.id, limit=query.limit, offset=(query.page - 1) * query.limit
        )
        return PaginatedResponse.build(
            [EvalRunSummary.model_validate(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get_run(self, run_id: uuid.UUID, *, actor: AuthenticatedUser) -> EvalRunDetail:
        """One run with its results. Resolves through the set's project like every read."""
        run = await self.runs.get(run_id)
        if run is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.EVAL_RUN_NOT_FOUND, "Eval run not found."
            )
        await self._load_set(run.set_id, actor, Permission.EVAL_READ)
        results = await self.results.list_for_run(run.id)
        return EvalRunDetail(
            **EvalRunSummary.model_validate(run).model_dump(),
            results=[self._result(row) for row in results],
        )

    async def _load_set(
        self, set_id: uuid.UUID, actor: AuthenticatedUser, permission: Permission
    ) -> tuple[EvalSet, Project]:
        """A set the caller may act on.

        `404 EVAL_SET_NOT_FOUND` for a set that does not exist, `404 PROJECT_NOT_FOUND`
        for a real set in a project the caller holds no membership on, `403` for a
        member whose role lacks `permission`. Both `404`s are safe: neither confirms a
        private project exists, because a random id and a non-member's id each answer
        `404` without naming anything.
        """
        eval_set = await self.sets.get(set_id)
        if eval_set is None:
            raise self._set_not_found()
        project = await access.require_readable_project(self.projects, eval_set.project_id, actor)
        access.require_permission(actor, project.id, permission)
        return eval_set, project

    @staticmethod
    def _set_not_found() -> AppError:
        return AppError(
            status.HTTP_404_NOT_FOUND, ErrorCode.EVAL_SET_NOT_FOUND, "Eval set not found."
        )

    @staticmethod
    def _summary(eval_set: EvalSet, *, latest_run: EvalRun | None) -> EvalSetSummary:
        return EvalSetSummary(
            id=eval_set.id,
            project_id=eval_set.project_id,
            name=eval_set.name,
            source_path=eval_set.source_path,
            requested_count=eval_set.requested_count,
            mix=eval_set.mix,  # type: ignore[arg-type]  # str column; pydantic coerces to EvalMix
            status=eval_set.status,  # type: ignore[arg-type]  # str column; coerced to EvalSetStatus
            error=eval_set.error,
            pair_count=eval_set.pair_count,
            indexed_generation=eval_set.indexed_generation,
            created_at=eval_set.created_at,
            latest_run=EvalRunSummary.model_validate(latest_run) if latest_run else None,
        )

    @staticmethod
    def _pair(pair: EvalPair) -> EvalPairRead:
        return EvalPairRead(
            id=pair.id,
            position=pair.position,
            question_type=pair.question_type,  # type: ignore[arg-type]  # str column; coerced
            question=pair.question,
            reference_answer=pair.reference_answer,
            source_file=pair.source_file,
            start_line=pair.start_line,
            end_line=pair.end_line,
            excluded=pair.excluded_at is not None,
        )

    @staticmethod
    def _result(result: EvalResult) -> EvalResultRead:
        return EvalResultRead(
            id=result.id,
            pair_id=result.pair_id,
            retrieval_hit=result.retrieval_hit,
            verdict=result.verdict,  # type: ignore[arg-type]  # str column; coerced to EvalVerdict
            judge_reason=result.judge_reason,
            answer=result.answer,
            grounding_warnings=result.grounding_warnings,
            retrieval_attempts=result.retrieval_attempts,
        )
