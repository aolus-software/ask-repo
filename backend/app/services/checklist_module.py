"""Module business rules.

Reads scope through `access.resolve_project_scope` and nothing else -- not
`created_by`, not `is_admin`. `created_by`/`is_admin` gate editing, deleting, and
re-pointing a module, and return `403` rather than `404` because module existence is
deliberately public (spec 2.5).
"""

import builtins
import logging
import time
import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.checklist import (
    ChecklistItemStatus,
    ChecklistModule,
    ChecklistModuleStatus,
)
from app.models.project import Project, ProjectStatus
from app.queue.protocol import ChecklistQueue
from app.queue.topics import ChecklistJobMessage
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_message import ChecklistMessageRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.project import ProjectRepository
from app.schemas.checklist import (
    ChecklistChangeSetResponse,
    ChecklistItemResponse,
    ChecklistMessageResponse,
    ChecklistModuleCreateRequest,
    ChecklistModuleDetailResponse,
    ChecklistModuleListQuery,
    ChecklistModuleResponse,
    ChecklistModuleUpdateRequest,
)
from app.schemas.pagination import PaginatedResponse

logger = logging.getLogger(__name__)

DEFAULT_SORT = "created_at"
MAX_CHANGE_SETS = 20
MAX_CHAT_MESSAGES = 200


class ChecklistModuleService:
    """Module CRUD, plus the pre-flight that decides whether a generation may start."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.modules = ChecklistModuleRepository(session)
        self.items = ChecklistItemRepository(session)
        self.change_sets = ChecklistChangeSetRepository(session)
        self.messages_repository = ChecklistMessageRepository(session)
        self.projects = ProjectRepository(session)

    async def list(
        self, query: ChecklistModuleListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[ChecklistModuleResponse]:
        """A page of modules the caller may read."""
        try:
            rows, total = await self.modules.list_page(
                scope=access.resolve_project_scope(actor),
                page=query.page,
                limit=query.limit,
                sort=query.sort or DEFAULT_SORT,
                descending=query.sort_direction == "desc",
                project_id=query.project_id,
                status=query.status.value if query.status else None,
                search=query.search,
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_SORT_FIELD, str(error)
            ) from error

        summaries = await self._summaries(rows)
        return PaginatedResponse.build(
            summaries, page=query.page, limit=query.limit, total_count=total
        )

    async def get(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> ChecklistModuleDetailResponse:
        """One module with its items, in grid order."""
        module = await self._require_readable(module_id, actor)
        summary = (await self._summaries([module]))[0]
        items = await self.items.list_for_module(module_id)
        return ChecklistModuleDetailResponse(
            **summary.model_dump(),
            items=[ChecklistItemResponse.model_validate(item) for item in items],
        )

    async def create(
        self, payload: ChecklistModuleCreateRequest, *, actor: AuthenticatedUser
    ) -> ChecklistModuleResponse:
        """Name a module against a project the caller may read."""
        project = await self._require_readable_project(payload.project_id, actor)
        self._require_indexed(project)
        module = await self.modules.add(
            ChecklistModule(
                id=uuid.uuid4(),
                project_id=project.id,
                created_by=actor.id,
                name=payload.name.strip(),
                source_path=payload.source_path.strip().strip("/"),
                status=ChecklistModuleStatus.EMPTY.value,
            )
        )
        await self.session.commit()
        return (await self._summaries([module]))[0]

    async def update(
        self,
        module_id: uuid.UUID,
        payload: ChecklistModuleUpdateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> ChecklistModuleResponse:
        """Rename or re-point a module. Gated on `created_by`/`is_admin`."""
        module = await self._require_readable(module_id, actor)
        self._require_destructive_rights(module, actor)
        if payload.name is not None:
            module.name = payload.name.strip()
        if payload.source_path is not None:
            module.source_path = payload.source_path.strip().strip("/")
        # `updated_at`'s `onupdate=func.now()` is a server-side expression: an ORM
        # UPDATE does not fetch it back via RETURNING the way an INSERT does, so it is
        # left expired on the Python object after commit. Setting it here, matching
        # `UserService.update`, avoids a lazy load that `_summaries` cannot perform
        # outside an awaited context.
        module.updated_at = datetime.now(UTC)
        await self.session.commit()
        return (await self._summaries([module]))[0]

    async def delete(self, module_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete a module and everything hanging off it (spec 3.7).

        Nothing reaches Qdrant: the checklist owns no vector points -- it *reads* the
        project's, and the project's own delete path hard-deletes those.
        """
        module = await self._require_readable(module_id, actor)
        self._require_destructive_rights(module, actor)
        await self.items.soft_delete_for_module(module_id)
        await self.change_sets.soft_delete_for_module(module_id)
        await self.messages_repository.soft_delete_for_module(module_id)
        await self.modules.soft_delete(module)
        await self.session.commit()

    async def request_generation(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser, queue: ChecklistQueue
    ) -> ChecklistModuleResponse:
        """Publish a generation job and return immediately.

        Every check that needs a status code happens here, before the publish. The
        embedding-model guard deliberately does **not** apply: it exists because a
        query embedded by a different model lands in a vector space the collection was
        never built in, and generation embeds nothing -- it filters and scrolls
        (spec 4.1).
        """
        module = await self._require_readable(module_id, actor)
        project = await self._require_readable_project(module.project_id, actor)
        self._require_indexed(project)

        if module.status == ChecklistModuleStatus.GENERATING.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.GENERATION_IN_PROGRESS,
                "A generation is already running for this module.",
            )
        if await self.change_sets.pending_for_module(module_id) is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.CHANGE_SET_PENDING,
                "Apply or discard the pending changes before generating again.",
            )

        job_id = uuid.uuid4()
        module.status = ChecklistModuleStatus.GENERATING.value
        module.error = None
        # See the matching comment in `update` -- `updated_at` needs the same
        # explicit set, or `_summaries` below hits an unawaited lazy load.
        module.updated_at = datetime.now(UTC)
        await self.session.commit()

        await queue.enqueue_checklist(
            ChecklistJobMessage(
                module_id=module_id,
                job_id=job_id,
                attempt=0,
                not_before_ms=int(time.time() * 1000),
                original_topic=self.settings.kafka_checklist_topic,
            )
        )
        logger.info("queued checklist generation for module %s as job %s", module_id, job_id)
        return (await self._summaries([module]))[0]

    async def change_sets_for(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> builtins.list[ChecklistChangeSetResponse]:
        """This module's change sets, newest first -- the audit trail."""
        await self._require_readable(module_id, actor)
        rows = await self.change_sets.list_for_module(module_id, limit=MAX_CHANGE_SETS)
        return [ChecklistChangeSetResponse.model_validate(row) for row in rows]

    async def messages(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> builtins.list[ChecklistMessageResponse]:
        """The module's shared chat. Readable by every authenticated user (spec 2.4)."""
        await self._require_readable(module_id, actor)
        rows = await self.messages_repository.list_for_module(module_id, limit=MAX_CHAT_MESSAGES)
        return [ChecklistMessageResponse.model_validate(row) for row in rows]

    async def _summaries(
        self, rows: builtins.list[ChecklistModule]
    ) -> builtins.list[ChecklistModuleResponse]:
        """Modules plus their counts, staleness, and pending badge, in three queries.

        Three regardless of how many rows: the counts, the pending ids, and the
        projects' active generations are each resolved in one statement. An N+1 here is
        the difference between one round trip and twenty-five on the list screen.
        """
        if not rows:
            return []
        module_ids = [row.id for row in rows]
        counts = await self.items.status_counts(module_ids=module_ids)
        pending = await self.change_sets.pending_module_ids(module_ids)
        generations = await self.projects.active_generations([row.project_id for row in rows])

        summaries: builtins.list[ChecklistModuleResponse] = []
        for row in rows:
            by_status = counts.get(row.id, {})
            active = generations.get(row.project_id)
            summaries.append(
                ChecklistModuleResponse(
                    id=row.id,
                    project_id=row.project_id,
                    created_by=row.created_by,
                    name=row.name,
                    source_path=row.source_path,
                    status=ChecklistModuleStatus(row.status),
                    error=row.error,
                    indexed_generation=row.indexed_generation,
                    last_generated_at=row.last_generated_at,
                    item_count=sum(by_status.values()),
                    pass_count=by_status.get(ChecklistItemStatus.PASS.value, 0),
                    fail_count=by_status.get(ChecklistItemStatus.FAIL.value, 0),
                    blocked_count=by_status.get(ChecklistItemStatus.BLOCKED.value, 0),
                    untested_count=by_status.get(ChecklistItemStatus.UNTESTED.value, 0),
                    stale=(
                        row.indexed_generation is not None
                        and active is not None
                        and row.indexed_generation < active
                    ),
                    pending_change_set_id=pending.get(row.id),
                    created_at=row.created_at,
                    updated_at=row.updated_at,
                )
            )
        return summaries

    async def _require_readable(
        self, module_id: uuid.UUID, actor: AuthenticatedUser
    ) -> ChecklistModule:
        """The module, if it is in the caller's scope. A miss is `404`."""
        module = await self.modules.get_in_scope(
            module_id, scope=access.resolve_project_scope(actor)
        )
        if module is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.CHECKLIST_MODULE_NOT_FOUND,
                "Checklist module not found.",
            )
        return module

    @staticmethod
    def _require_destructive_rights(module: ChecklistModule, actor: AuthenticatedUser) -> None:
        """`created_by` or an admin. `403`, because existence is not a secret."""
        if module.created_by != actor.id and not actor.is_admin:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                ErrorCode.NOT_CHECKLIST_OWNER,
                "Only the person who created this module, or an admin, can change it.",
            )

    async def _require_readable_project(
        self, project_id: uuid.UUID, actor: AuthenticatedUser
    ) -> Project:
        """The project, if it is in the caller's scope."""
        scope = access.resolve_project_scope(actor)
        project = await self.projects.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    @staticmethod
    def _require_indexed(project: Project) -> None:
        """There has to be an index to enumerate.

        No embedding-model check, deliberately -- see `request_generation`.
        """
        if project.status != ProjectStatus.READY.value or not project.embedding_collection:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PROJECT_NOT_READY,
                "This project is not indexed yet. Wait for indexing to finish.",
            )
