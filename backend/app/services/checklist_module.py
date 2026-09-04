"""Module business rules.

Reads scope through `access.resolve_project_scope` and nothing else -- not
`created_by`, not `is_admin`. `created_by`/`is_admin` gate editing, deleting, and
re-pointing a module, and return `403` rather than `404` because module existence is
deliberately public (spec 2.5).
"""

import asyncio
import builtins
import logging
import time
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.checklist import (
    ChangeSetOrigin,
    ChangeSetStatus,
    ChecklistChangeSet,
    ChecklistItemStatus,
    ChecklistMessage,
    ChecklistModule,
    ChecklistModuleStatus,
)
from app.models.conversation import FinishReason, MessageRole
from app.models.project import Project, ProjectStatus
from app.queue.protocol import ChecklistQueue
from app.queue.topics import ChecklistJobMessage
from app.rag.answerer import Answerer
from app.rag.prompts import ExistingItem, Turn
from app.repositories.checklist_change_set import ChecklistChangeSetRepository
from app.repositories.checklist_item import ChecklistItemRepository
from app.repositories.checklist_message import ChecklistMessageRepository
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.project import ProjectRepository
from app.schemas.checklist import (
    ChangeSetEvent,
    ChecklistChangeSetResponse,
    ChecklistItemResponse,
    ChecklistMessageCreateRequest,
    ChecklistMessageResponse,
    ChecklistModuleCreateRequest,
    ChecklistModuleDetailResponse,
    ChecklistModuleListQuery,
    ChecklistModuleResponse,
    ChecklistModuleUpdateRequest,
)
from app.schemas.conversation import (
    KEEP_ALIVE,
    CitationPayload,
    CitationsEvent,
    DoneEvent,
    ErrorEvent,
    StreamEvent,
    TokenEvent,
    encode_event,
)
from app.schemas.pagination import PaginatedResponse

logger = logging.getLogger(__name__)

DEFAULT_SORT = "created_at"
MAX_CHANGE_SETS = 20
MAX_CHAT_MESSAGES = 200
KEEP_ALIVE_SECONDS = 15.0


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

    async def prepare_turn(
        self,
        module_id: uuid.UUID,
        payload: ChecklistMessageCreateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> "ChecklistTurnContext":
        """Everything that can still set a status code, before any bytes are sent.

        The same split `ConversationService.prepare_turn` makes, for the same reason:
        once SSE headers are sent the status is fixed at `200`. The embedding-model
        guard **does** apply here, unlike generation, because chat retrieves.

        Open to every authenticated user: the chat is shared, so `created_by` records
        who spoke rather than who may speak (spec 2.4).
        """
        module = await self._require_readable(module_id, actor)
        project = await self._require_readable_project(module.project_id, actor)
        self._require_answerable(project)

        user_message = ChecklistMessage(
            id=uuid.uuid4(),
            module_id=module_id,
            role=MessageRole.USER.value,
            content=payload.question,
            created_by=actor.id,
        )
        await self.messages_repository.add(user_message)
        await self.session.commit()

        return ChecklistTurnContext(
            module_id=module_id,
            module_name=module.name,
            project_id=project.id,
            generation=project.active_generation,
            # Verbatim from the row, never recomputed from current settings.
            collection=project.embedding_collection or "",
            question=payload.question,
            # Mapped off the ORM rows, matching `ConversationService._history`: the
            # dataclass field is `list[Turn]`, and the stream runs on its own
            # session, so nothing here may carry a row bound to this one.
            history=[
                Turn(role=message.role, content=message.content)
                for message in await self.messages_repository.recent_turns(
                    module_id, limit=self.settings.rag_history_turns
                )
            ],
            existing_items=[
                ExistingItem(
                    id=str(item.id),
                    feature=item.feature,
                    test_name=item.test_name,
                    expected_result=item.expected_result,
                    kind=item.kind,
                )
                for item in await self.items.list_for_module(module_id)
            ],
            user_message_id=user_message.id,
            # Both minted here. The assistant row is written once, at termination, and
            # the terminator has to name it; the change set is written under the shield,
            # so its id cannot come from the insert either (spec 5.2).
            assistant_message_id=uuid.uuid4(),
            change_set_id=uuid.uuid4(),
            created_by=actor.id,
        )

    def _require_answerable(self, project: Project) -> None:
        """Refuse to answer from an index that is absent or built by another model.

        The embedding check is the one that would otherwise fail silently: swap one
        768-dimensional model for another and Qdrant accepts the query happily,
        returning nearest neighbours in a space the collection was never built in.
        Retrieval becomes noise, the answers stay fluent and cited, and nothing
        anywhere reports an error (`.claude/rules/rag.md`).
        """
        if project.status != ProjectStatus.READY.value or not project.embedding_collection:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PROJECT_NOT_READY,
                "This project is not indexed yet. Wait for indexing to finish.",
            )
        if project.embedding_model != self.settings.embedding_model:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EMBEDDING_MODEL_CHANGED,
                (
                    f"This project was indexed with {project.embedding_model!r} but this "
                    f"instance now embeds with {self.settings.embedding_model!r}. Reindex "
                    "the project, or change the embedding model back."
                ),
            )

    async def _summaries(
        self, rows: builtins.list[ChecklistModule]
    ) -> builtins.list[ChecklistModuleResponse]:
        """Modules plus their counts, staleness, project name and pending badge.

        Three queries regardless of how many rows: the counts, the pending ids, and the
        projects' names and active generations are each resolved in one statement. An
        N+1 here is the difference between one round trip and twenty-five on the list
        screen.
        """
        if not rows:
            return []
        module_ids = [row.id for row in rows]
        counts = await self.items.status_counts(module_ids=module_ids)
        pending = await self.change_sets.pending_module_ids(module_ids)
        projects = await self.projects.names_and_generations([row.project_id for row in rows])

        summaries: builtins.list[ChecklistModuleResponse] = []
        for row in rows:
            by_status = counts.get(row.id, {})
            project = projects.get(row.project_id)
            summaries.append(
                ChecklistModuleResponse(
                    id=row.id,
                    project_id=row.project_id,
                    project_name=project.name if project else "",
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
                        and project is not None
                        and row.indexed_generation < project.active_generation
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


@dataclass(frozen=True, slots=True)
class ChecklistTurnContext:
    """Everything the stream needs, resolved before a byte is sent.

    A frozen snapshot rather than a live session handle: the stream runs on its own
    session (see `stream_checklist_turn`), so anything it needs from the request's
    session has to be read out here.
    """

    module_id: uuid.UUID
    module_name: str
    project_id: uuid.UUID
    generation: int
    collection: str
    question: str
    history: builtins.list[Turn]
    existing_items: builtins.list[ExistingItem]
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    change_set_id: uuid.UUID
    created_by: uuid.UUID


async def stream_checklist_turn(
    *,
    context: ChecklistTurnContext,
    answerer: Answerer,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> AsyncGenerator[bytes]:
    """Forward the answerer's events as SSE, and record the turn exactly once.

    Its own session, from the sessionmaker rather than from `Depends`: FastAPI closes
    `yield` dependencies through the request's `AsyncExitStack`, and a persistence
    guarantee should not rest on when that runs relative to a streaming body -- least
    of all on the cancellation path.
    """
    parts: builtins.list[str] = []
    citations: builtins.list[CitationPayload] = []
    proposal: ChangeSetEvent | None = None
    # The default, not a fallback: reaching the end of this generator without a
    # terminator means the client went away.
    finish_reason = FinishReason.DISCONNECTED

    events = answerer.answer(
        question=context.question,
        history=context.history,
        project_id=context.project_id,
        generation=context.generation,
        message_id=context.assistant_message_id,
        existing_items=context.existing_items,
        change_set_id=context.change_set_id,
        module_name=context.module_name,
    )
    iterator = events.__aiter__()
    pending: asyncio.Task[StreamEvent] | None = None
    try:
        while True:
            pending = asyncio.ensure_future(anext(iterator))
            # `asyncio.wait` rather than `wait_for`: `wait_for` cancels its task on
            # timeout, throwing the pending event away instead of waiting longer.
            while not (await asyncio.wait({pending}, timeout=KEEP_ALIVE_SECONDS))[0]:
                yield KEEP_ALIVE
            try:
                event = pending.result()
            except StopAsyncIteration:
                break
            pending = None

            if isinstance(event, TokenEvent):
                parts.append(event.text)
            elif isinstance(event, CitationsEvent):
                citations = event.citations
            elif isinstance(event, ChangeSetEvent):
                proposal = event
            elif isinstance(event, DoneEvent | ErrorEvent):
                finish_reason = event.finish_reason
            yield encode_event(event)
    finally:
        # Shielded, because a disconnect arrives as CancelledError and every `await`
        # in a cancelled task raises it again immediately -- so an unshielded cleanup
        # runs none of itself, losing the partial answer and leaking the answerer's
        # concurrency permit with it.
        await asyncio.shield(
            _finalise_checklist_turn(
                events=events,
                pending=pending,
                context=context,
                content="".join(parts),
                citations=citations,
                proposal=proposal,
                finish_reason=finish_reason,
                sessionmaker=sessionmaker,
                model_id=model_id,
            )
        )


async def _finalise_checklist_turn(
    *,
    events: AsyncGenerator[StreamEvent],
    pending: asyncio.Task[StreamEvent] | None,
    context: ChecklistTurnContext,
    content: str,
    citations: builtins.list[CitationPayload],
    proposal: ChangeSetEvent | None,
    finish_reason: FinishReason,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> None:
    """Close the answerer and write the assistant row, plus any proposal.

    Order matters. The in-flight `anext` is cancelled and awaited before `aclose`,
    because closing a generator that is still running raises `RuntimeError` -- and that
    close is what releases the concurrency permit. Skip it and the next answers queue
    behind a slot nobody holds.

    A proposal is stored only if one arrived. An empty pending change set would put a
    Review-changes badge on a module with nothing to review.
    """
    if pending is not None:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
    with suppress(Exception):
        await events.aclose()

    async with sessionmaker() as session:
        session.add(
            ChecklistMessage(
                id=context.assistant_message_id,
                module_id=context.module_id,
                role=MessageRole.ASSISTANT.value,
                content=content,
                # Stored snake_case: this is a database column, and camelCase is the
                # wire only. `ChecklistMessageResponse` re-aliases it on the way out.
                citations=[citation.model_dump() for citation in citations] or None,
                model=model_id,
                finish_reason=finish_reason.value,
                created_by=context.created_by,
            )
        )
        # Flushed before the change set: `ChecklistChangeSet.message_id` is a real
        # foreign key, and the two rows have no ORM `relationship()` between them for
        # the unit of work to order by. Without this, the pending `ChecklistChangeSet`
        # insert can autoflush ahead of the message it references.
        await session.flush()
        if proposal is not None:
            session.add(
                ChecklistChangeSet(
                    id=context.change_set_id,
                    module_id=context.module_id,
                    origin=ChangeSetOrigin.CHAT.value,
                    message_id=context.assistant_message_id,
                    summary=proposal.summary,
                    operations=[
                        operation.model_dump(by_alias=True) for operation in proposal.operations
                    ],
                    status=ChangeSetStatus.PENDING.value,
                    created_by=context.created_by,
                )
            )
            await ChecklistModuleRepository(session).mark_in_review(context.module_id)
        await session.commit()

    if finish_reason is not FinishReason.STOP:
        logger.warning(
            "checklist turn %s on module %s ended as %s after %d characters",
            context.assistant_message_id,
            context.module_id,
            finish_reason.value,
            len(content),
        )
