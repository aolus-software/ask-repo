"""Private conversations and the answer stream.

Reads here invert the rule that governs projects. A project is visible to every
authenticated user; a conversation is visible only to the person who had it, and a
request for anyone else's returns `404` — never `403`, and never widened by
`is_admin` (`docs/PRD.md` §4.2).
"""

import asyncio
import uuid
from collections.abc import Callable
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from langchain_core.language_models import BaseChatModel

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.ingestion.embedder import Embedder
from app.ingestion.vector_store import build_store_factory
from app.rag.answerer import Answerer
from app.rag.retriever import CodeRetriever
from app.schemas.conversation import (
    ConversationCreateRequest,
    ConversationDetailResponse,
    ConversationListQuery,
    ConversationResponse,
    MessageCreateRequest,
)
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import PaginatedResponse
from app.services.conversation import ConversationService, stream_turn

router = APIRouter(prefix="/conversations", tags=["Conversations"])

AnswererFactory = Callable[[str], Answerer]

SSE_HEADERS = {
    "Cache-Control": "no-cache",
    "Connection": "keep-alive",
    # Without this a buffering proxy accumulates the whole stream and delivers it
    # in one piece, which defeats the entire point of streaming.
    "X-Accel-Buffering": "no",
}


def get_embedder(request: Request) -> Embedder:
    """The embedder built during application startup.

    Its `dimensions` is never probed in this process and is never read: creating a
    collection needs the width, querying one does not.
    """
    embedder: Embedder | None = getattr(request.app.state, "embedder", None)
    if embedder is None:
        raise RuntimeError("embedder is not configured; check the app lifespan")
    return embedder


def get_chat_model(request: Request) -> BaseChatModel:
    """The chat model built during application startup."""
    model: BaseChatModel | None = getattr(request.app.state, "chat_model", None)
    if model is None:
        raise RuntimeError("chat model is not configured; check the app lifespan")
    return model


def get_answer_semaphore(request: Request) -> asyncio.Semaphore:
    """The instance-wide generation cap (`docs/PRD.md` §9)."""
    semaphore: asyncio.Semaphore | None = getattr(request.app.state, "answer_semaphore", None)
    if semaphore is None:
        raise RuntimeError("answer semaphore is not configured; check the app lifespan")
    return semaphore


def get_answerer_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    chat_model: Annotated[BaseChatModel, Depends(get_chat_model)],
    semaphore: Annotated[asyncio.Semaphore, Depends(get_answer_semaphore)],
) -> AnswererFactory:
    """Collection name in, a configured answerer out.

    A factory rather than one answerer, for the same reason the store is one: the
    collection a project's points live in is on the project's own row, so it is not
    known until the request has loaded it. Overridden wholesale in tests, which is
    what keeps Qdrant and Ollama out of the suite.
    """
    store_for = build_store_factory(settings)

    def answerer_for(collection: str) -> Answerer:
        return Answerer(
            retriever=CodeRetriever(
                store=store_for(collection),
                embedder=embedder,
                top_k=settings.rag_top_k,
                max_chars=settings.rag_context_max_chars,
                min_score=settings.rag_min_score,
            ),
            chat_model=chat_model,
            model_id=settings.chat_model,
            semaphore=semaphore,
            settings=settings,
        )

    return answerer_for


def get_conversation_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> ConversationService:
    """Provide the service with a request-scoped session."""
    return ConversationService(session, settings)


ConversationServiceDep = Annotated[ConversationService, Depends(get_conversation_service)]
AnswererFactoryDep = Annotated[AnswererFactory, Depends(get_answerer_factory)]


@router.get(
    "",
    response_model=PaginatedResponse[ConversationResponse],
    status_code=status.HTTP_200_OK,
    summary="List your own conversations",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_conversations(
    current_user: CurrentUser,
    service: ConversationServiceDep,
    query: Annotated[ConversationListQuery, Query()],
) -> PaginatedResponse[ConversationResponse]:
    return await service.list(query, actor=current_user, project_id=query.project_id)


@router.post(
    "",
    response_model=ConversationResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Open a conversation against a project",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def create_conversation(
    payload: ConversationCreateRequest, current_user: CurrentUser, service: ConversationServiceDep
) -> ConversationResponse:
    return await service.create(payload, actor=current_user)


@router.get(
    "/{conversation_id}",
    response_model=ConversationDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one conversation and its messages",
    # No 403: a conversation the caller does not own is a 404, because its
    # existence is private (`docs/PRD.md` §4.2).
    responses={code: ERROR_RESPONSES[code] for code in (401, 404, 422)},
)
async def get_conversation(
    conversation_id: uuid.UUID, current_user: CurrentUser, service: ConversationServiceDep
) -> ConversationDetailResponse:
    return await service.get(conversation_id, actor=current_user)


@router.delete(
    "/{conversation_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete one of your conversations",
    responses={code: ERROR_RESPONSES[code] for code in (401, 404, 422)},
)
async def delete_conversation(
    conversation_id: uuid.UUID, current_user: CurrentUser, service: ConversationServiceDep
) -> None:
    await service.delete(conversation_id, actor=current_user)


@router.post(
    "/{conversation_id}/messages",
    status_code=status.HTTP_200_OK,
    summary="Ask a question and stream the answer",
    # No `response_model`: the body is `text/event-stream`, whose payload models are
    # in `app/schemas/conversation.py` and are checked by `tests/test_api_model.py`
    # rather than by FastAPI.
    response_class=StreamingResponse,
    responses={code: ERROR_RESPONSES[code] for code in (401, 404, 409, 422)},
)
async def ask_question(
    conversation_id: uuid.UUID,
    payload: MessageCreateRequest,
    current_user: CurrentUser,
    service: ConversationServiceDep,
    answerer_factory: AnswererFactoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Validate, persist the question, then stream the answer.

    The one route in the codebase that does two things, and unavoidably so: once
    the response body has started there is no status code left to set, so every
    decision that needs one has to happen in `prepare_turn` first. All of the policy
    is still in the service — the route only chooses the transport.
    """
    context = await service.prepare_turn(conversation_id, payload, actor=current_user)
    return StreamingResponse(
        stream_turn(
            context=context,
            answerer=answerer_factory(context.collection),
            sessionmaker=get_sessionmaker(),
            model_id=settings.chat_model,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
