"""QA pair lifecycle, and one re-run of a saved question.

Two responsibilities, split at the point where the HTTP status code stops being
available — the same split `ConversationService` makes and for the same reason.
`prepare_rerun` runs everything that can legitimately return something other than
`200`; `stream_rerun` runs afterwards, inside the response body, where the only way
to report a failure is an event.
"""

import asyncio
import builtins
import logging
import uuid
from collections.abc import AsyncGenerator
from contextlib import suppress
from dataclasses import dataclass
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy import func, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.conversation import FinishReason, Message, MessageRole
from app.models.project import Project, ProjectStatus
from app.models.qa_pair import QAPair, QASource, QAStatus
from app.rag.answerer import Answerer
from app.repositories.conversation import ConversationRepository, MessageRepository
from app.repositories.project import ProjectRepository
from app.repositories.qa_pair import QAPairRepository
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
from app.schemas.qa_pair import (
    MAX_TAG_CHARS,
    PendingRunPayload,
    QAPairCreateRequest,
    QAPairDetailResponse,
    QAPairListQuery,
    QAPairResponse,
    QAPairStatusRequest,
    QAPairUpdateRequest,
)

logger = logging.getLogger(__name__)

DEFAULT_SORT = "created_at"


def normalise_tags(tags: list[str]) -> list[str]:
    """Trimmed, lowercased, deduplicated, empties dropped, order preserved.

    Applied on every write so the tag filter never has to guess at casing, and so
    `distinct_tags` returns a list a human recognises rather than three spellings
    of the same word.
    """
    seen: dict[str, None] = {}
    for tag in tags:
        cleaned = tag.strip().lower()[:MAX_TAG_CHARS]
        if cleaned:
            seen.setdefault(cleaned, None)
    return list(seen)


@dataclass(frozen=True, slots=True)
class RerunContext:
    """Everything the stream needs, flattened off the ORM.

    Plain data on purpose: the stream runs on its own session, and ORM instances
    bound to the request's session would be detached — or lazily reloaded — by the
    time it uses them.
    """

    pair_id: uuid.UUID
    project_id: uuid.UUID
    generation: int
    collection: str
    question: str


class QAPairService:
    """Business rules for QA pairs. Owns its transactions."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self._pairs = QAPairRepository(session)
        self._conversations = ConversationRepository(session)
        self._messages = MessageRepository(session)
        self._projects = ProjectRepository(session)

    async def create(
        self, payload: QAPairCreateRequest, *, actor: AuthenticatedUser
    ) -> QAPairDetailResponse:
        """Publish a finished answer to the shared list.

        The content is copied out of the message rows, never taken from the request.
        A QA pair is readable by every user on the instance, so its text must come
        from a model through the server — and this is the only place
        `finish_reason` can be checked, because in a request body a truncated answer
        and a short one are the same string (spec §2.6).
        """
        answer = await self._require_publishable_message(payload.message_id, actor)
        question = await self._preceding_question(answer)
        conversation = await self._conversations.get_for_owner(
            answer.conversation_id, access.resolve_conversation_owner(actor)
        )
        # `_require_publishable_message` already proved this, so it cannot be None.
        assert conversation is not None

        pair = QAPair(
            id=uuid.uuid4(),
            project_id=conversation.project_id,
            created_by=actor.id,
            module=payload.module,
            question=question,
            answer=answer.content,
            # Seeded: the person saving is publishing an answer they judged good, so
            # that answer is the expected result until someone says otherwise.
            reference_answer=answer.content,
            citations=answer.citations,
            tags=normalise_tags(payload.tags),
            source=QASource.MANUAL.value,
            status=QAStatus.UNREVIEWED.value,
            model=answer.model,
            last_run_at=answer.created_at,
        )
        await self._pairs.add(pair)
        await self.session.commit()
        return self._detail(pair)

    async def get(self, pair_id: uuid.UUID, *, actor: AuthenticatedUser) -> QAPairDetailResponse:
        """One pair, if the caller may read its project."""
        return self._detail(await self._require_readable(pair_id, actor))

    async def list(
        self, query: QAPairListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[QAPairResponse]:
        """A page of pairs the caller may read."""
        try:
            rows, total = await self._pairs.list_page(
                scope=access.resolve_project_scope(actor),
                page=query.page,
                limit=query.limit,
                sort=query.sort or DEFAULT_SORT,
                descending=query.sort_direction == "desc",
                project_id=query.project_id,
                module=query.module,
                tag=query.tag,
                source=query.source.value if query.source else None,
                status=query.status.value if query.status else None,
                created_by=query.created_by,
                search=query.search,
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_SORT_FIELD, str(error)
            ) from error
        return PaginatedResponse.build(
            [self._summary(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def tags(self, *, actor: AuthenticatedUser) -> builtins.list[str]:
        """Every tag in use across the caller's scope, for the filter combobox.

        `builtins.list` because this class defines a method named `list`, so inside
        the class body the bare name is that method rather than the type — the same
        note `ConversationService` carries.
        """
        return await self._pairs.distinct_tags(scope=access.resolve_project_scope(actor))

    # ---- guards -------------------------------------------------------------

    async def _require_readable(self, pair_id: uuid.UUID, actor: AuthenticatedUser) -> QAPair:
        """The pair, if its project is in the caller's scope. `404` otherwise."""
        pair = await self._pairs.get(pair_id)
        scope = access.resolve_project_scope(actor)
        if pair is None or not (scope.unrestricted or pair.project_id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.QA_PAIR_NOT_FOUND, "QA pair not found."
            )
        return pair

    def _require_destructive_rights(self, pair: QAPair, actor: AuthenticatedUser) -> None:
        """`created_by` or admin, per `docs/PRD.md:338` — the same rule as projects.

        `403`, not `404`: a QA pair is a shared instance asset and its existence is
        deliberately not secret (`.claude/rules/response-api.md`).
        """
        if not (actor.is_admin or pair.created_by == actor.id):
            raise AppError(
                status.HTTP_403_FORBIDDEN,
                ErrorCode.NOT_QA_PAIR_OWNER,
                "Only the person who saved this pair, or an admin, can change it.",
            )

    async def _require_publishable_message(
        self, message_id: uuid.UUID, actor: AuthenticatedUser
    ) -> Message:
        """A finished assistant message in a conversation the caller owns.

        Every miss is `404`, including someone else's conversation: a `403` there
        would confirm the conversation exists, which is the `403`/`404` distinction
        running backwards on the one resource whose existence is private.
        """
        message = await self._messages.get(message_id)
        if message is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.MESSAGE_NOT_FOUND, "Message not found."
            )
        conversation = await self._conversations.get_for_owner(
            message.conversation_id, access.resolve_conversation_owner(actor)
        )
        if conversation is None:
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.MESSAGE_NOT_FOUND, "Message not found."
            )
        if message.role != MessageRole.ASSISTANT.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ANSWER_INCOMPLETE,
                "Only an assistant answer can be saved to the QA List.",
            )
        if message.finish_reason != FinishReason.STOP.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ANSWER_INCOMPLETE,
                "This answer did not finish, so it cannot be published to the team.",
            )
        return message

    async def _preceding_question(self, answer: Message) -> str:
        """The user message this answer replied to."""
        messages = await self._messages.list_for_conversation(answer.conversation_id)
        question = None
        for message in messages:
            if message.id == answer.id:
                break
            if message.role == MessageRole.USER.value:
                question = message.content
        if question is None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ANSWER_INCOMPLETE,
                "This answer has no question before it.",
            )
        return question

    # ---- projection ---------------------------------------------------------

    def _summary(self, pair: QAPair) -> QAPairResponse:
        """A row. The pending run is a flag here, not a payload."""
        return QAPairResponse(
            id=pair.id,
            project_id=pair.project_id,
            created_by=pair.created_by,
            module=pair.module,
            question=pair.question,
            answer=pair.answer,
            reference_answer=pair.reference_answer,
            tags=list(pair.tags),
            source=QASource(pair.source),
            status=QAStatus(pair.status),
            reviewed_by=pair.reviewed_by,
            reviewed_at=pair.reviewed_at,
            model=pair.model,
            eval_score=pair.eval_score,
            last_run_at=pair.last_run_at,
            has_pending_run=pair.pending_run_at is not None,
            created_at=pair.created_at,
            updated_at=pair.updated_at,
        )

    def _detail(self, pair: QAPair) -> QAPairDetailResponse:
        """A row plus its citations and its pending run."""
        pending = None
        if pair.pending_run_at is not None and pair.pending_answer is not None:
            pending = PendingRunPayload(
                answer=pair.pending_answer,
                citations=[
                    CitationPayload.model_validate(citation)
                    for citation in pair.pending_citations or []
                ]
                or None,
                model=pair.pending_model,
                finish_reason=pair.pending_finish_reason or FinishReason.ERROR.value,
                run_at=pair.pending_run_at,
            )
        return QAPairDetailResponse(
            **self._summary(pair).model_dump(),
            citations=[
                CitationPayload.model_validate(citation) for citation in pair.citations or []
            ]
            or None,
            pending_run=pending,
        )

    async def update(
        self, pair_id: uuid.UUID, payload: QAPairUpdateRequest, *, actor: AuthenticatedUser
    ) -> QAPairDetailResponse:
        """Edit the fields a human owns.

        `answer` is not among them. It only ever arrives from a model, through
        `accept_rerun` — spec §2.5.
        """
        pair = await self._require_readable(pair_id, actor)
        self._require_destructive_rights(pair, actor)

        # `exclude_unset` so a PATCH naming one field does not blank the rest: an
        # omitted key and an explicit null are different requests.
        changes = payload.model_dump(exclude_unset=True)
        if "module" in changes:
            pair.module = changes["module"]
        if "question" in changes and changes["question"] is not None:
            pair.question = changes["question"]
        if "reference_answer" in changes:
            pair.reference_answer = changes["reference_answer"]
        if "tags" in changes and changes["tags"] is not None:
            pair.tags = normalise_tags(changes["tags"])

        # `updated_at`'s `onupdate=func.now()` is a server-side expression: an ORM
        # UPDATE does not fetch it back via RETURNING the way an INSERT does, so it
        # is left expired on the Python object after commit. Setting it here avoids a
        # lazy load that the projection below cannot perform outside an awaited
        # context. Same reason as `UserService.update`.
        pair.updated_at = datetime.now(UTC)

        await self.session.commit()
        return self._detail(pair)

    async def set_status(
        self, pair_id: uuid.UUID, payload: QAPairStatusRequest, *, actor: AuthenticatedUser
    ) -> QAPairDetailResponse:
        """Record the verdict. Open to every authenticated user.

        Deliberately not gated on `created_by` — `docs/PRD.md:338` says any user may
        verify a pair, and the point of a shared regression set is that a colleague
        can mark a stale answer as failing without tracking down whoever saved it.
        """
        pair = await self._require_readable(pair_id, actor)
        pair.status = payload.status.value
        if payload.status is QAStatus.UNREVIEWED:
            pair.reviewed_by = None
            pair.reviewed_at = None
        else:
            pair.reviewed_by = actor.id
            pair.reviewed_at = datetime.now(UTC)
        # See `update` above: a server-side `onupdate` is left expired after an ORM
        # UPDATE, and the projection cannot lazy-load it outside an awaited context.
        pair.updated_at = datetime.now(UTC)
        await self.session.commit()
        return self._detail(pair)

    async def delete(self, pair_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete a pair. No Qdrant work — its citations are copies and it
        owns no vector points, so `docs/PRD.md` §5.1's hard-delete rule does not
        apply here."""
        pair = await self._require_readable(pair_id, actor)
        self._require_destructive_rights(pair, actor)
        await self._pairs.soft_delete(pair)
        await self.session.commit()

    async def prepare_rerun(self, pair_id: uuid.UUID, *, actor: AuthenticatedUser) -> RerunContext:
        """Everything that can still set a status code, before any bytes are sent.

        Once SSE headers are sent the status is fixed at `200`, so nothing here may
        be deferred into the stream. The same split `ConversationService.prepare_turn`
        makes, for the same reason.
        """
        pair = await self._require_readable(pair_id, actor)
        self._require_destructive_rights(pair, actor)
        project = await self._require_readable_project(pair.project_id, actor)
        self._require_answerable(project)

        return RerunContext(
            pair_id=pair.id,
            project_id=project.id,
            generation=project.active_generation,
            # Verbatim from the row, never recomputed from current settings: the
            # width is probed at worker startup and is not available in this
            # process, and a project indexed before a provider switch legitimately
            # lives in a different collection from the one settings would name.
            collection=project.embedding_collection or "",
            question=pair.question,
        )

    async def accept_rerun(
        self, pair_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> QAPairDetailResponse:
        """Promote the pending run into the stored answer.

        The verdict resets. A human who marked this pair `pass` vouched for *that
        text*; if the text is replaced and the verdict survives, `status` stops
        meaning "a person read this and it was right", which is the only thing it is
        for (spec §5.4).
        """
        pair = await self._require_readable(pair_id, actor)
        self._require_destructive_rights(pair, actor)

        if pair.pending_run_at is None or pair.pending_answer is None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.NO_PENDING_RUN,
                "There is no re-run waiting on this pair.",
            )
        if pair.pending_finish_reason != FinishReason.STOP.value:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.ANSWER_INCOMPLETE,
                "That re-run did not finish, so it cannot replace the stored answer.",
            )

        pair.answer = pair.pending_answer
        pair.citations = pair.pending_citations
        pair.model = pair.pending_model
        pair.last_run_at = pair.pending_run_at
        pair.status = QAStatus.UNREVIEWED.value
        pair.reviewed_by = None
        pair.reviewed_at = None
        self._clear_pending(pair)
        # See `update` above: a server-side `onupdate` is left expired after an ORM
        # UPDATE, and the projection below cannot lazy-load it outside an awaited
        # context.
        pair.updated_at = datetime.now(UTC)

        await self.session.commit()
        return self._detail(pair)

    async def discard_rerun(self, pair_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Throw the pending run away. The stored answer is untouched."""
        pair = await self._require_readable(pair_id, actor)
        self._require_destructive_rights(pair, actor)
        if pair.pending_run_at is None:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.NO_PENDING_RUN,
                "There is no re-run waiting on this pair.",
            )
        self._clear_pending(pair)
        await self.session.commit()

    @staticmethod
    def _clear_pending(pair: QAPair) -> None:
        """Empty all five slot columns together, so none is ever left behind."""
        pair.pending_answer = None
        pair.pending_citations = None
        pair.pending_model = None
        pair.pending_finish_reason = None
        pair.pending_run_at = None

    async def _require_readable_project(
        self, project_id: uuid.UUID, actor: AuthenticatedUser
    ) -> Project:
        """The project, if it is in the caller's scope."""
        scope = access.resolve_project_scope(actor)
        project = await self._projects.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    def _require_answerable(self, project: Project) -> None:
        """Refuse to answer from an index that is absent or built by another model.

        The embedding check is the one that would otherwise fail silently — see
        `.claude/rules/rag.md`. Mirrors `ConversationService._require_answerable`
        deliberately rather than sharing it: the two are the same rule today, and a
        premature helper would hide the day they stop being.
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


KEEP_ALIVE_SECONDS = 15.0


async def stream_rerun(
    *,
    context: RerunContext,
    answerer: Answerer,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> AsyncGenerator[bytes]:
    """Forward the answerer's events as SSE, and record the run exactly once.

    Its own session, from the sessionmaker rather than from `Depends`: FastAPI
    closes `yield` dependencies through the request's `AsyncExitStack`, and a
    persistence guarantee should not rest on when that runs relative to a streaming
    body — least of all on the cancellation path.

    `history=[]` is correct rather than convenient: a saved question is standalone
    by construction. The classify node still runs, so a saved question that now
    routes out of scope reports that in `done` — the point of a re-run is that it
    takes the same path the original answer took.
    """
    parts: list[str] = []
    citations: list[CitationPayload] = []
    # The default, not a fallback: reaching the end of this generator without a
    # terminator means the client went away.
    finish_reason = FinishReason.DISCONNECTED

    events = answerer.answer(
        question=context.question,
        history=[],
        project_id=context.project_id,
        generation=context.generation,
        message_id=None,
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
            elif isinstance(event, DoneEvent | ErrorEvent):
                finish_reason = event.finish_reason
            yield encode_event(event)
    finally:
        # Shielded, because a disconnect arrives as CancelledError and every `await`
        # in a cancelled task raises it again immediately — so an unshielded cleanup
        # runs none of itself, losing the partial run and leaking the answerer's
        # concurrency permit with it.
        await asyncio.shield(
            _store_pending_run(
                events=events,
                pending=pending,
                context=context,
                content="".join(parts),
                citations=citations,
                finish_reason=finish_reason,
                sessionmaker=sessionmaker,
                model_id=model_id,
            )
        )


async def _store_pending_run(
    *,
    events: AsyncGenerator[StreamEvent],
    pending: asyncio.Task[StreamEvent] | None,
    context: RerunContext,
    content: str,
    citations: list[CitationPayload],
    finish_reason: FinishReason,
    sessionmaker: async_sessionmaker[AsyncSession],
    model_id: str,
) -> None:
    """Close the answerer and write the pending slot.

    Order matters. The in-flight `anext` is cancelled and awaited before `aclose`,
    because closing a generator that is still running raises `RuntimeError` — and
    that close is what releases the concurrency semaphore the answerer holds.

    A partial run is stored, not discarded: `docs/PRD.md` §4.2's "a broken stream
    keeps what arrived" applies here too, and `pending_finish_reason` is what stops
    it ever being published (spec §2.5).
    """
    if pending is not None:
        pending.cancel()
        with suppress(asyncio.CancelledError, StopAsyncIteration):
            await pending
    with suppress(Exception):
        await events.aclose()

    async with sessionmaker() as session:
        await session.execute(
            update(QAPair)
            .where(QAPair.id == context.pair_id)
            .values(
                pending_answer=content,
                pending_citations=[citation.model_dump() for citation in citations] or None,
                pending_model=model_id,
                pending_finish_reason=finish_reason.value,
                pending_run_at=func.now(),
                updated_at=func.now(),
            )
        )
        await session.commit()
    if finish_reason is not FinishReason.STOP:
        logger.warning(
            "Re-run of QA pair %s ended as %s after %d characters",
            context.pair_id,
            finish_reason.value,
            len(content),
        )
