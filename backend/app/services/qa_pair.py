"""QA pair lifecycle, and one re-run of a saved question.

Two responsibilities, split at the point where the HTTP status code stops being
available — the same split `ConversationService` makes and for the same reason.
`prepare_rerun` runs everything that can legitimately return something other than
`200`; `stream_rerun` runs afterwards, inside the response body, where the only way
to report a failure is an event.
"""

import builtins
import logging
import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.models.conversation import FinishReason, Message, MessageRole
from app.models.project import Project
from app.models.qa_pair import QAPair, QASource, QAStatus
from app.repositories.conversation import ConversationRepository, MessageRepository
from app.repositories.project import ProjectRepository
from app.repositories.qa_pair import QAPairRepository
from app.schemas.conversation import CitationPayload
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
        assert conversation is not None  # noqa: S101 -- narrowing for the type checker

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

    async def get(
        self, pair_id: uuid.UUID, *, actor: AuthenticatedUser
    ) -> QAPairDetailResponse:
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

    async def _require_readable(
        self, pair_id: uuid.UUID, actor: AuthenticatedUser
    ) -> QAPair:
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
