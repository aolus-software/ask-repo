"""Checklist modules: the unit of generation and of review.

Access matches projects and inverts conversations: every authenticated user reads every
module and every module's chat, and `created_by` gates editing and deleting rather than
reading (spec 2.4, 2.5).
"""

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status
from fastapi.responses import StreamingResponse
from langchain_core.language_models import BaseChatModel

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.conversations import (
    SSE_HEADERS,
    AnswererFactory,
    get_answer_semaphore,
    get_chat_model,
    get_embedder,
)
from app.api.routes.projects import get_indexed_path_reader
from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.ingestion.embedder import Embedder
from app.ingestion.vector_store import build_store_factory
from app.queue.protocol import ChecklistQueue
from app.rag.answerer import Answerer
from app.rag.retriever import CodeRetriever
from app.schemas.checklist import (
    ChecklistChangeSetResponse,
    ChecklistMessageCreateRequest,
    ChecklistMessageResponse,
    ChecklistModuleCreateRequest,
    ChecklistModuleDetailResponse,
    ChecklistModuleListQuery,
    ChecklistModuleResponse,
    ChecklistModuleUpdateRequest,
)
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import PaginatedResponse
from app.services.checklist_module import ChecklistModuleService, stream_checklist_turn
from app.services.indexed_path import IndexedPathReader

router = APIRouter(prefix="/checklist-modules", tags=["Checklist Modules"])


def get_checklist_module_service(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    indexed_paths: Annotated[IndexedPathReader, Depends(get_indexed_path_reader)],
) -> ChecklistModuleService:
    """Provide the service with a request-scoped session.

    The reader comes from the projects router so that refusing an unindexed
    `source_path` here and browsing the tree there share one cache.
    """
    return ChecklistModuleService(session, settings, indexed_paths=indexed_paths)


def get_checklist_queue(request: Request) -> ChecklistQueue:
    """The Kafka producer built during application startup.

    The same object `get_ingestion_queue` returns, narrowed to the checklist half of
    its surface: `KafkaIngestionQueue` satisfies both protocols. A dependency of its
    own so tests override this route's queue without touching the ingestion one.
    """
    queue: ChecklistQueue | None = getattr(request.app.state, "ingestion_queue", None)
    if queue is None:
        raise RuntimeError("the job queue is not configured; check the app lifespan")
    return queue


def get_proposing_answerer_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    chat_model: Annotated[BaseChatModel, Depends(get_chat_model)],
    semaphore: Annotated[asyncio.Semaphore, Depends(get_answer_semaphore)],
) -> AnswererFactory:
    """Collection name in, a *proposing* answerer out.

    Built here rather than reusing `get_answerer_factory` because the graph shape
    differs -- but it takes the SAME semaphore instance, which is what keeps a burst of
    refinement turns from starving the Ask screen.
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
            propose_target="checklist",
        )

    return answerer_for


ChecklistModuleServiceDep = Annotated[ChecklistModuleService, Depends(get_checklist_module_service)]
ChecklistQueueDep = Annotated[ChecklistQueue, Depends(get_checklist_queue)]
ProposingAnswererFactoryDep = Annotated[AnswererFactory, Depends(get_proposing_answerer_factory)]


@router.get(
    "",
    response_model=PaginatedResponse[ChecklistModuleResponse],
    status_code=status.HTTP_200_OK,
    summary="List checklist modules",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_checklist_modules(
    current_user: CurrentUser,
    service: ChecklistModuleServiceDep,
    query: Annotated[ChecklistModuleListQuery, Query()],
) -> PaginatedResponse[ChecklistModuleResponse]:
    """A page of modules the caller may read, with their pass/fail counts."""
    return await service.list(query, actor=current_user)


@router.post(
    "",
    response_model=ChecklistModuleResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a checklist module",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def create_checklist_module(
    payload: ChecklistModuleCreateRequest,
    current_user: CurrentUser,
    service: ChecklistModuleServiceDep,
) -> ChecklistModuleResponse:
    """Name a module and point it at a path in the indexed repository."""
    return await service.create(payload, actor=current_user)


@router.get(
    "/{module_id}",
    response_model=ChecklistModuleDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one checklist module and its items",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def get_checklist_module(
    module_id: uuid.UUID, current_user: CurrentUser, service: ChecklistModuleServiceDep
) -> ChecklistModuleDetailResponse:
    """One module with its test cases, grouped by feature."""
    return await service.get(module_id, actor=current_user)


@router.patch(
    "/{module_id}",
    response_model=ChecklistModuleResponse,
    status_code=status.HTTP_200_OK,
    summary="Rename or re-point a checklist module",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def update_checklist_module(
    module_id: uuid.UUID,
    payload: ChecklistModuleUpdateRequest,
    current_user: CurrentUser,
    service: ChecklistModuleServiceDep,
) -> ChecklistModuleResponse:
    """Change the module's name or the path it covers."""
    return await service.update(module_id, payload, actor=current_user)


@router.delete(
    "/{module_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a checklist module",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def delete_checklist_module(
    module_id: uuid.UUID, current_user: CurrentUser, service: ChecklistModuleServiceDep
) -> Response:
    """Soft-delete the module, its items, its change sets, and its chat."""
    await service.delete(module_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post(
    "/{module_id}/generate",
    response_model=ChecklistModuleResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate a checklist for this module",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def generate_checklist(
    module_id: uuid.UUID,
    current_user: CurrentUser,
    service: ChecklistModuleServiceDep,
    queue: ChecklistQueueDep,
) -> ChecklistModuleResponse:
    """Publish a generation job and return. The result is a change set to review."""
    return await service.request_generation(module_id, actor=current_user, queue=queue)


@router.get(
    "/{module_id}/change-sets",
    response_model=list[ChecklistChangeSetResponse],
    status_code=status.HTTP_200_OK,
    summary="List a module's change sets",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def list_change_sets(
    module_id: uuid.UUID, current_user: CurrentUser, service: ChecklistModuleServiceDep
) -> list[ChecklistChangeSetResponse]:
    """Newest first: the audit trail of every proposal against this module."""
    return await service.change_sets_for(module_id, actor=current_user)


@router.get(
    "/{module_id}/messages",
    response_model=list[ChecklistMessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Read a module's refinement chat",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def list_messages(
    module_id: uuid.UUID, current_user: CurrentUser, service: ChecklistModuleServiceDep
) -> list[ChecklistMessageResponse]:
    """Shared, not private: the chat is the justification record for the checklist."""
    return await service.messages(module_id, actor=current_user)


@router.post(
    "/{module_id}/messages",
    status_code=status.HTTP_200_OK,
    summary="Refine the checklist by chat, streaming the reply",
    # No `response_model`: the body is `text/event-stream`, whose payload models live
    # in `app/schemas/conversation.py` and `app/schemas/checklist.py` and are checked
    # by `tests/test_api_model.py` rather than by FastAPI.
    response_class=StreamingResponse,
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def refine_checklist(
    module_id: uuid.UUID,
    payload: ChecklistMessageCreateRequest,
    current_user: CurrentUser,
    service: ChecklistModuleServiceDep,
    answerer_factory: ProposingAnswererFactoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Validate, persist the question, then stream the answer.

    The second route in the codebase that does two things, for the same reason
    `ask_question` is the first: once the response body has started there is no status
    code left to set, so everything that needs one happens in `prepare_turn`. All of
    the policy is still in the service -- the route only chooses the transport.
    """
    context = await service.prepare_turn(module_id, payload, actor=current_user)
    return StreamingResponse(
        stream_checklist_turn(
            context=context,
            answerer=answerer_factory(context.collection),
            sessionmaker=get_sessionmaker(),
            model_id=settings.chat_model,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )
