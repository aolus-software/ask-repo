"""Mock-data dataset business rules: reads, the generation trigger, and the chat.

Reads scope through `access.resolve_project_scope` and nothing else, exactly like
`ChecklistModuleService` -- not `created_by`, not `is_admin`. Applying/discarding is
open to any authenticated user (`app/services/mock_data_change_set.py`); this service
never gates a read on ownership.
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
from app.models.checklist import ChangeSetOrigin, ChangeSetStatus, ChecklistModule
from app.models.conversation import FinishReason, MessageRole
from app.models.mock_data import (
    MockDataChangeSet,
    MockDataDataset,
    MockDataDatasetStatus,
    MockDataMessage,
    MockDataRecord,
)
from app.models.project import Project, ProjectStatus
from app.queue.protocol import MockDataQueue
from app.queue.topics import MockDataJobMessage
from app.rag.answerer import Answerer
from app.rag.prompts import ExistingRecord, Turn
from app.repositories.checklist_module import ChecklistModuleRepository
from app.repositories.mock_data_change_set import MockDataChangeSetRepository
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from app.repositories.mock_data_message import MockDataMessageRepository
from app.repositories.mock_data_record import MockDataRecordRepository
from app.repositories.project import ProjectRepository
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
from app.schemas.mock_data import (
    MockDataChangeSetEvent,
    MockDataChangeSetResponse,
    MockDataDatasetDetailResponse,
    MockDataDatasetResponse,
    MockDataGenerationRequest,
    MockDataMessageCreateRequest,
    MockDataMessageResponse,
    MockDataRecordResponse,
)
from app.services.mock_data_export import build_mock_data_json, build_mock_data_workbook

logger = logging.getLogger(__name__)

MAX_CHANGE_SETS = 20
MAX_CHAT_MESSAGES = 200
KEEP_ALIVE_SECONDS = 15.0


class MockDataDatasetService:
    """Dataset reads, the generation trigger, and the pre-flight for the chat."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.datasets = MockDataDatasetRepository(session)
        self.records = MockDataRecordRepository(session)
        self.change_sets = MockDataChangeSetRepository(session)
        self.messages_repository = MockDataMessageRepository(session)
        self.modules = ChecklistModuleRepository(session)
        self.projects = ProjectRepository(session)

    async def get(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> MockDataDatasetDetailResponse:
        """A module's mock dataset, with its records. Empty summary before the first
        generation -- there is no dataset row yet, and that is not a 404."""
        module = await self._require_readable_module(module_id, actor)
        project = await self.projects.get(module.project_id)
        dataset = await self.datasets.get_by_module(module_id)
        records = await self.records.list_for_module(module_id) if dataset else []
        pending = await self.change_sets.pending_for_module(module_id)
        summary = self._summary(
            module_id,
            dataset=dataset,
            project=project,
            record_count=len(records),
            pending_change_set_id=pending.id if pending else None,
        )
        return MockDataDatasetDetailResponse(
            **summary.model_dump(),
            records=[MockDataRecordResponse.model_validate(record) for record in records],
        )

    async def request_generation(
        self,
        module_id: uuid.UUID,
        payload: MockDataGenerationRequest,
        *,
        actor: AuthenticatedUser,
        queue: MockDataQueue,
    ) -> MockDataDatasetResponse:
        """Publish a generation job and return immediately. No embedding-model guard,
        for the same reason `ChecklistModuleService.request_generation` has none:
        generation filters and scrolls, it embeds nothing."""
        module = await self._require_readable_module(module_id, actor)
        project = await self._require_readable_project(module.project_id, actor)
        self._require_indexed(project)

        dataset = await self.datasets.get_or_create_for_module(module_id)
        if dataset.status == MockDataDatasetStatus.GENERATING.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.MOCK_DATA_GENERATION_IN_PROGRESS,
                "A generation is already running for this module's mock dataset.",
            )
        if await self.change_sets.pending_for_module(module_id) is not None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.MOCK_DATA_CHANGE_SET_PENDING,
                "Apply or discard the pending changes before generating again.",
            )

        job_id = uuid.uuid4()
        dataset.status = MockDataDatasetStatus.GENERATING.value
        dataset.error = None
        dataset.updated_at = datetime.now(UTC)
        await self.session.commit()

        await queue.enqueue_mock_data(
            MockDataJobMessage(
                dataset_id=dataset.id,
                job_id=job_id,
                attempt=0,
                not_before_ms=int(time.time() * 1000),
                original_topic=self.settings.kafka_mock_data_topic,
                count=payload.count,
            )
        )
        logger.info(
            "queued mock-data generation for dataset %s (module %s) as job %s",
            dataset.id,
            module_id,
            job_id,
        )
        records = await self.records.list_for_module(module_id)
        # No pending change set to report: the check above already refused this call
        # if one existed, and nothing between there and here can create one.
        return self._summary(
            module_id,
            dataset=dataset,
            project=project,
            record_count=len(records),
            pending_change_set_id=None,
        )

    async def change_sets_for(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> builtins.list[MockDataChangeSetResponse]:
        """This module's mock-data change sets, newest first."""
        await self._require_readable_module(module_id, actor)
        rows = await self.change_sets.list_for_module(module_id, limit=MAX_CHANGE_SETS)
        return [MockDataChangeSetResponse.model_validate(row) for row in rows]

    async def messages(
        self, module_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> builtins.list[MockDataMessageResponse]:
        """The module's mock-data chat. Readable by every authenticated user."""
        await self._require_readable_module(module_id, actor)
        rows = await self.messages_repository.list_for_module(module_id, limit=MAX_CHAT_MESSAGES)
        return [MockDataMessageResponse.model_validate(row) for row in rows]

    async def export_json(self, module_id: uuid.UUID, *, actor: AuthenticatedUser) -> bytes:
        """Every applied record of one module, as a JSON array of field maps."""
        await self._require_readable_module(module_id, actor)
        records = await self._records_within_cap(module_id)
        return build_mock_data_json(records)

    async def export_xlsx(self, module_id: uuid.UUID, *, actor: AuthenticatedUser) -> bytes:
        """Every applied record of one module, as a spreadsheet."""
        await self._require_readable_module(module_id, actor)
        records = await self._records_within_cap(module_id)
        return build_mock_data_workbook(records)

    async def _records_within_cap(self, module_id: uuid.UUID) -> builtins.list[MockDataRecord]:
        """This module's records, or a `409` if there are more than the export cap allows."""
        cap = self.settings.mock_data_export_max_rows
        records = await self.records.list_for_module(module_id)
        if len(records) > cap:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.EXPORT_TOO_LARGE,
                f"This module has more than {cap} mock data records. Delete some and try again.",
            )
        return records

    async def delete_record(self, record_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Delete one record. Gated on `created_by`/`is_admin`, `403` because module
        (and therefore dataset) existence is deliberately public."""
        record = await self.records.get(record_id)
        if record is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.MOCK_DATA_RECORD_NOT_FOUND,
                "Mock data record not found.",
            )
        # Module-scope readability first: a record in a project the caller cannot see
        # must 404, not 403 -- the same order `ChecklistItemService.delete` follows.
        await self._require_readable_module(record.checklist_module_id, actor)
        if record.created_by != actor.id and not actor.is_admin:
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                ErrorCode.NOT_MOCK_DATA_RECORD_OWNER,
                "Only the person who created this record, or an admin, can delete it.",
            )
        await self.records.soft_delete(record)
        await self.session.commit()

    async def prepare_turn(
        self,
        module_id: uuid.UUID,
        payload: MockDataMessageCreateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> "MockDataTurnContext":
        """Everything that can still set a status code, before any bytes are sent.
        Same split `ChecklistModuleService.prepare_turn` makes, for the same reason."""
        module = await self._require_readable_module(module_id, actor)
        project = await self._require_readable_project(module.project_id, actor)
        self._require_answerable(project)

        # A dataset row must exist before the chat can propose against it or mark
        # itself `review` -- lazily created here, matching `request_generation`.
        dataset = await self.datasets.get_or_create_for_module(module_id)
        if dataset.status == MockDataDatasetStatus.GENERATING.value:
            # A worker holds this dataset's lease right now, and `generating` is the
            # only signal the reconcile sweep has that a run is still alive (it stays
            # `generating` throughout, so status alone cannot say whose lease it is).
            # Writing `review` over it here -- what `_finalise_mock_data_turn` would do
            # if this turn proposed anything -- would blind that sweep to a worker
            # that later dies, and would leave two pending change sets if the worker
            # finishes normally instead.
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.MOCK_DATA_GENERATION_IN_PROGRESS,
                "A generation is already running for this module's mock dataset. "
                "Wait for it to finish before refining by chat.",
            )

        user_message = MockDataMessage(
            id=uuid.uuid4(),
            checklist_module_id=module_id,
            role=MessageRole.USER.value,
            content=payload.question,
            created_by=actor.id,
        )
        await self.messages_repository.add(user_message)
        await self.session.commit()

        return MockDataTurnContext(
            module_id=module_id,
            module_name=module.name,
            dataset_id=dataset.id,
            project_id=project.id,
            generation=project.active_generation,
            collection=project.embedding_collection or "",
            question=payload.question,
            history=[
                Turn(role=message.role, content=message.content)
                for message in await self.messages_repository.recent_turns(
                    module_id, limit=self.settings.rag_history_turns
                )
            ],
            existing_records=[
                ExistingRecord(id=str(record.id), fields=record.fields)
                for record in await self.records.list_for_module(module_id)
            ],
            user_message_id=user_message.id,
            assistant_message_id=uuid.uuid4(),
            change_set_id=uuid.uuid4(),
            created_by=actor.id,
        )

    def _summary(
        self,
        module_id: uuid.UUID,
        *,
        dataset: MockDataDataset | None,
        project: Project | None,
        record_count: int,
        pending_change_set_id: uuid.UUID | None,
    ) -> MockDataDatasetResponse:
        """The dataset row, or a synthetic `empty` one before the first generation."""
        status_value = (
            MockDataDatasetStatus(dataset.status) if dataset else MockDataDatasetStatus.EMPTY
        )
        return MockDataDatasetResponse(
            id=dataset.id if dataset else module_id,
            checklist_module_id=module_id,
            status=status_value,
            error=dataset.error if dataset else None,
            indexed_generation=dataset.indexed_generation if dataset else None,
            last_generated_at=dataset.last_generated_at if dataset else None,
            stale=bool(
                dataset
                and dataset.indexed_generation is not None
                and project is not None
                and dataset.indexed_generation < project.active_generation
            ),
            record_count=record_count,
            pending_change_set_id=pending_change_set_id,
            created_at=dataset.created_at if dataset else datetime.now(UTC),
            updated_at=dataset.updated_at if dataset else datetime.now(UTC),
        )

    def _require_answerable(self, project: Project) -> None:
        """Same guard `ChecklistModuleService._require_answerable` applies -- chat
        retrieves, so the embedding-model check does apply here."""
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

    async def _require_readable_module(
        self, module_id: uuid.UUID, actor: AuthenticatedUser
    ) -> ChecklistModule:
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

    async def _require_readable_project(
        self, project_id: uuid.UUID, actor: AuthenticatedUser
    ) -> Project:
        scope = access.resolve_project_scope(actor)
        project = await self.projects.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    @staticmethod
    def _require_indexed(project: Project) -> None:
        if project.status != ProjectStatus.READY.value or not project.embedding_collection:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PROJECT_NOT_READY,
                "This project is not indexed yet. Wait for indexing to finish.",
            )


@dataclass(frozen=True, slots=True)
class MockDataTurnContext:
    """Everything the mock-data chat stream needs, resolved before a byte is sent."""

    module_id: uuid.UUID
    module_name: str
    dataset_id: uuid.UUID
    project_id: uuid.UUID
    generation: int
    collection: str
    question: str
    history: builtins.list[Turn]
    existing_records: builtins.list[ExistingRecord]
    user_message_id: uuid.UUID
    assistant_message_id: uuid.UUID
    change_set_id: uuid.UUID
    created_by: uuid.UUID


async def stream_mock_data_turn(
    *,
    context: MockDataTurnContext,
    answerer: Answerer,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> AsyncGenerator[bytes]:
    """Forward the answerer's events as SSE, and record the turn exactly once.

    Structurally identical to `stream_checklist_turn` -- its own session, the shielded
    finalise, the same ordering contract. See that function's docstring for why each
    piece exists; nothing here changes the reasoning, only the content type.
    """
    parts: builtins.list[str] = []
    citations: builtins.list[CitationPayload] = []
    proposal: MockDataChangeSetEvent | None = None
    finish_reason = FinishReason.DISCONNECTED

    events = answerer.answer(
        question=context.question,
        history=context.history,
        project_id=context.project_id,
        generation=context.generation,
        message_id=context.assistant_message_id,
        existing_records=context.existing_records,
        change_set_id=context.change_set_id,
        module_name=context.module_name,
    )
    iterator = events.__aiter__()
    pending: asyncio.Task[StreamEvent] | None = None
    try:
        while True:
            pending = asyncio.ensure_future(anext(iterator))
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
            elif isinstance(event, MockDataChangeSetEvent):
                proposal = event
            elif isinstance(event, DoneEvent | ErrorEvent):
                finish_reason = event.finish_reason
            yield encode_event(event)
    finally:
        await asyncio.shield(
            _finalise_mock_data_turn(
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


async def _finalise_mock_data_turn(
    *,
    events: AsyncGenerator[StreamEvent],
    pending: asyncio.Task[StreamEvent] | None,
    context: MockDataTurnContext,
    content: str,
    citations: builtins.list[CitationPayload],
    proposal: MockDataChangeSetEvent | None,
    finish_reason: FinishReason,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> None:
    """Close the answerer and write the assistant row, plus any proposal.

    Same ordering as `_finalise_checklist_turn`: cancel and await the in-flight
    `anext` before `aclose`, because closing a still-running generator raises
    `RuntimeError` -- and that close is what releases the concurrency permit.
    """
    if pending is not None:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
    with suppress(Exception):
        await events.aclose()

    async with sessionmaker() as session:
        session.add(
            MockDataMessage(
                id=context.assistant_message_id,
                checklist_module_id=context.module_id,
                role=MessageRole.ASSISTANT.value,
                content=content,
                citations=[citation.model_dump() for citation in citations] or None,
                model=model_id,
                finish_reason=finish_reason.value,
                created_by=context.created_by,
            )
        )
        await session.flush()
        if proposal is not None:
            session.add(
                MockDataChangeSet(
                    id=context.change_set_id,
                    checklist_module_id=context.module_id,
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
            await MockDataDatasetRepository(session).mark_in_review(context.dataset_id)
        await session.commit()

    if finish_reason is not FinishReason.STOP:
        logger.warning(
            "mock-data turn %s on module %s ended as %s after %d characters",
            context.assistant_message_id,
            context.module_id,
            finish_reason.value,
            len(content),
        )
