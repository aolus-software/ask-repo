"""Conversation lifecycle and one turn of question answering.

Two responsibilities, split at the point where the HTTP status code stops being
available. `ConversationService.prepare_turn` runs everything that can legitimately
return something other than `200` — ownership, project readiness, the embedding
guard — and commits the user's question. `stream_turn` runs afterwards, inside the
response body, where the only way to report a failure is an event.
"""

import asyncio
import builtins
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.conversation import (
    MAX_TITLE_CHARS,
    Conversation,
    FinishReason,
    Message,
    MessageRole,
)
from app.models.project import Project, ProjectStatus
from app.rag.answerer import Answerer
from app.rag.prompts import Turn
from app.repositories.conversation import ConversationRepository, MessageRepository
from app.repositories.project import ProjectRepository
from app.schemas.conversation import (
    KEEP_ALIVE,
    CitationPayload,
    CitationsEvent,
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationResponse,
    DoneEvent,
    ErrorEvent,
    MessageCreateRequest,
    MessageResponse,
    StreamEvent,
    TokenEvent,
    encode_event,
)
from app.schemas.pagination import ListQuery, PaginatedResponse

logger = logging.getLogger(__name__)

DEFAULT_SORT = "updated_at"
KEEP_ALIVE_SECONDS = 15.0


@dataclass(frozen=True, slots=True)
class TurnContext:
    """Everything the stream needs, flattened off the ORM.

    Plain data on purpose: the stream runs on its own session, and ORM instances
    bound to the request's session would be detached — or worse, lazily reloaded —
    by the time it uses them.
    """

    conversation_id: uuid.UUID
    project_id: uuid.UUID
    generation: int
    collection: str
    question: str
    history: list[Turn]
    message_id: uuid.UUID


class ConversationService:
    """Business rules for conversations. Owns its transactions."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._projects = ProjectRepository(session)

    async def create(
        self, payload: ConversationCreateRequest, *, actor: AuthenticatedUser
    ) -> ConversationResponse:
        """Open a conversation against a project the caller may read."""
        await self._require_readable_project(payload.project_id, actor)
        conversation = Conversation(
            id=uuid.uuid4(),
            user_id=access.resolve_conversation_owner(actor),
            project_id=payload.project_id,
        )
        await self._conversations.add(conversation)
        await self.session.commit()
        return ConversationResponse.model_validate(conversation, from_attributes=True)

    async def list(
        self,
        query: ListQuery,
        *,
        actor: AuthenticatedUser,
        project_id: uuid.UUID | None = None,
    ) -> PaginatedResponse[ConversationResponse]:
        """A page of the caller's own conversations."""
        try:
            rows, total = await self._conversations.list_page(
                owner_id=access.resolve_conversation_owner(actor),
                project_id=project_id,
                search=query.search,
                page=query.page,
                limit=query.limit,
                sort=query.sort or DEFAULT_SORT,
                descending=query.sort_direction == "desc",
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_SORT_FIELD, str(error)
            ) from error
        return PaginatedResponse.build(
            [ConversationResponse.model_validate(row, from_attributes=True) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get(
        self, conversation_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> ConversationDetailResponse:
        """One conversation and its messages, oldest first."""
        conversation = await self._require_own(conversation_id, actor)
        messages = await self._messages.list_for_conversation(conversation.id)
        return ConversationDetailResponse(
            id=conversation.id,
            project_id=conversation.project_id,
            title=conversation.title,
            created_at=conversation.created_at,
            updated_at=conversation.updated_at,
            messages=[
                MessageResponse.model_validate(message, from_attributes=True)
                for message in messages
            ],
        )

    async def delete(self, conversation_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete a conversation.

        Messages need no sweep: they carry no `deleted_at` and are reachable only
        through their conversation.
        """
        conversation = await self._require_own(conversation_id, actor)
        await self._conversations.soft_delete(conversation)
        await self.session.commit()

    async def prepare_turn(
        self,
        conversation_id: uuid.UUID,
        payload: MessageCreateRequest,
        *,
        actor: AuthenticatedUser,
    ) -> TurnContext:
        """Everything that can still set a status code, then commit the question.

        Once SSE headers are sent the status is fixed at `200`, so nothing here may
        be deferred into the stream. The user's message is committed before
        generation starts because the partial-answer guarantee requires the question
        to survive regardless of what happens next.
        """
        conversation = await self._require_own(conversation_id, actor)
        project = await self._require_readable_project(conversation.project_id, actor)
        self._require_answerable(project)

        await self._messages.add(
            Message(
                id=uuid.uuid4(),
                conversation_id=conversation.id,
                role=MessageRole.USER.value,
                content=payload.question,
            )
        )
        if conversation.title is None:
            conversation.title = _derive_title(payload.question)
        await self.session.commit()

        return TurnContext(
            conversation_id=conversation.id,
            project_id=project.id,
            generation=project.active_generation,
            collection=project.embedding_collection or "",
            question=payload.question,
            history=await self._history(conversation.id),
            message_id=uuid.uuid4(),
        )

    # `builtins.list`, and it has to be: this class defines a method named `list`,
    # so inside the class body the bare name is that method rather than the type. At
    # runtime an unquoted `list[Turn]` raises `TypeError: 'function' object is not
    # subscriptable` on import; quoting silences that but leaves mypy resolving the
    # same shadowed name. Any later method here returning a list needs the same.
    async def _history(self, conversation_id: uuid.UUID) -> builtins.list[Turn]:
        """The sliding window, minus the turn just written and minus anything that
        did not finish.

        `+ 1` because `prepare_turn` has already committed the new question, which
        belongs in the prompt as the question, not as history.

        Turns whose assistant message did not end in `stop` are dropped: replaying a
        truncated answer invites the model to continue someone else's half-sentence
        as though it were its own.
        """
        recent = await self._messages.recent_turns(
            conversation_id, limit=self.settings.rag_history_turns + 1
        )
        return [
            Turn(role=message.role, content=message.content)
            for message in recent[:-1]
            if message.role == MessageRole.USER.value
            or message.finish_reason == FinishReason.STOP.value
        ]

    async def _require_own(
        self, conversation_id: uuid.UUID, actor: AuthenticatedUser
    ) -> Conversation:
        """Load a conversation the caller owns, or raise `404`.

        `404` rather than `403`, and with no `is_admin` branch: `docs/PRD.md` §4.2
        makes conversation existence private, so confirming it to a non-owner is the
        leak the status code exists to prevent.
        """
        conversation = await self._conversations.get_for_owner(
            conversation_id, access.resolve_conversation_owner(actor)
        )
        if conversation is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND,
                ErrorCode.CONVERSATION_NOT_FOUND,
                "Conversation not found.",
            )
        return conversation

    async def _require_readable_project(
        self, project_id: uuid.UUID, actor: AuthenticatedUser
    ) -> Project:
        """The project, scoped through the access resolver and nowhere else."""
        scope = access.resolve_project_scope(actor)
        project = await self._projects.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    def _require_answerable(self, project: Project) -> None:
        """Refuse to answer from an index that is absent or built by another model.

        The embedding check is the one that would otherwise fail silently. Swap one
        768-wide model for another and Qdrant accepts the query, returns its nearest
        neighbours in a space this collection was never built in, and the model
        writes a fluent, cited answer about noise — with no error anywhere.
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


def _derive_title(question: str) -> str:
    """A thread title from the first question, whitespace collapsed and bounded."""
    collapsed = " ".join(question.split())
    return collapsed[:MAX_TITLE_CHARS]


async def stream_turn(
    *,
    context: TurnContext,
    answerer: Answerer,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> AsyncGenerator[bytes]:
    """Forward the answerer's events as SSE, and record the outcome exactly once.

    Its own session, from the sessionmaker rather than from `Depends`: FastAPI closes
    `yield` dependencies through the request's `AsyncExitStack`, and a persistence
    guarantee should not rest on when that runs relative to a streaming body — least
    of all on the cancellation path, where the request scope is already unwinding.

    The assistant row is written once, at termination, rather than updated per token:
    a per-token `UPDATE` is thousands of writes for a row nobody reads until it is
    finished. If the API process is killed mid-stream nothing persists, and in that
    case the client received nothing either.
    """
    parts: list[str] = []
    citations: list[CitationPayload] = []
    cited: list[int] = []
    # The default, not a fallback: reaching the end of this generator without a
    # terminator means the client went away.
    finish_reason = FinishReason.DISCONNECTED

    events = answerer.answer(
        question=context.question,
        history=context.history,
        project_id=context.project_id,
        generation=context.generation,
        message_id=context.message_id,
    )
    iterator = events.__aiter__()
    pending: asyncio.Task[StreamEvent] | None = None
    try:
        while True:
            pending = asyncio.ensure_future(anext(iterator))
            # `asyncio.wait` rather than `wait_for`: `wait_for` cancels its task on
            # timeout, which would throw the pending event away instead of waiting
            # longer for it. Caddy reaps an idle SSE connection, and the gap before
            # the first token spans a rewrite and a retrieval.
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
            elif isinstance(event, DoneEvent):
                finish_reason = event.finish_reason
                cited = event.cited_indexes
            elif isinstance(event, ErrorEvent):
                finish_reason = event.finish_reason
            yield encode_event(event)
    finally:
        # Shielded, because a disconnect arrives as CancelledError and every `await`
        # in a cancelled task raises it again immediately — so an unshielded cleanup
        # here runs none of itself, losing the partial answer this whole design
        # exists to keep and leaking the answerer's concurrency permit with it.
        await asyncio.shield(
            _finalise(
                events=events,
                pending=pending,
                context=context,
                content="".join(parts),
                citations=citations,
                cited=cited,
                finish_reason=finish_reason,
                sessionmaker=sessionmaker,
                model_id=model_id,
            )
        )


async def _finalise(
    *,
    events: AsyncGenerator[StreamEvent],
    pending: asyncio.Task[StreamEvent] | None,
    context: TurnContext,
    content: str,
    citations: list[CitationPayload],
    cited: list[int],
    finish_reason: FinishReason,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> None:
    """Close the answerer and write the assistant row.

    Order matters. The in-flight `anext` is cancelled and awaited before `aclose`,
    because closing a generator that is still running raises `RuntimeError` — and
    the close is what releases the concurrency semaphore the answerer holds.
    """
    if pending is not None:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
    with suppress(Exception):
        await events.aclose()

    cited_set = set(cited)
    stored = [
        # Stored snake_case: this is a database column, and `docs/PRD.md` §5.1 keeps
        # camelCase on the wire only. `MessageResponse` re-aliases it on the way out.
        citation.model_copy(update={"cited": citation.index in cited_set}).model_dump()
        for citation in citations
    ]
    async with sessionmaker() as session:
        session.add(
            Message(
                id=context.message_id,
                conversation_id=context.conversation_id,
                role=MessageRole.ASSISTANT.value,
                content=content,
                citations=stored or None,
                model=model_id,
                finish_reason=finish_reason.value,
            )
        )
        await session.commit()
    if finish_reason is not FinishReason.STOP:
        logger.warning(
            "Turn %s in conversation %s ended as %s after %d characters",
            context.message_id,
            context.conversation_id,
            finish_reason.value,
            len(content),
        )
