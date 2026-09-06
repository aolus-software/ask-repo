"""A module's mock dataset: reads, the generation trigger, the chat, and export.

Access matches `checklist_modules.py`: every authenticated user reads every module's
mock dataset and chat; `created_by`/`is_admin` gates nothing here except one-record
deletes (`mock_data_records.py`).
"""

import asyncio
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Request, Response, status
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
from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.ingestion.embedder import Embedder
from app.ingestion.vector_store import build_store_factory
from app.queue.protocol import MockDataQueue
from app.rag.answerer import Answerer
from app.rag.retriever import CodeRetriever
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.mock_data import (
    MockDataChangeSetResponse,
    MockDataDatasetDetailResponse,
    MockDataDatasetResponse,
    MockDataGenerationRequest,
    MockDataMessageCreateRequest,
    MockDataMessageResponse,
)
from app.services.mock_data_dataset import MockDataDatasetService, stream_mock_data_turn

router = APIRouter(prefix="/checklist-modules", tags=["Mock Data Datasets"])

JSON_MEDIA_TYPE = "application/json"
XLSX_MEDIA_TYPE = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"

# Avoids ruff B008 (a default evaluated once at import, which is exactly what is
# wanted for an all-defaults body) -- same pattern as
# `checklist_change_sets.py`'s `APPLY_EVERY_OPERATION`.
DEFAULT_GENERATION_REQUEST = MockDataGenerationRequest()


def get_mock_data_dataset_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> MockDataDatasetService:
    """Provide the service with a request-scoped session."""
    return MockDataDatasetService(session, settings)


def get_mock_data_queue(request: Request) -> MockDataQueue:
    """The Kafka producer built during application startup, narrowed to the mock-data
    half of its surface. `KafkaIngestionQueue` satisfies this protocol too -- same
    pattern as `get_checklist_queue` in `checklist_modules.py`."""
    queue: MockDataQueue | None = getattr(request.app.state, "ingestion_queue", None)
    if queue is None:
        raise RuntimeError("the job queue is not configured; check the app lifespan")
    return queue


def get_proposing_mock_data_answerer_factory(
    settings: Annotated[Settings, Depends(get_settings)],
    embedder: Annotated[Embedder, Depends(get_embedder)],
    chat_model: Annotated[BaseChatModel, Depends(get_chat_model)],
    semaphore: Annotated[asyncio.Semaphore, Depends(get_answer_semaphore)],
) -> AnswererFactory:
    """Collection name in, a mock-data-proposing answerer out. Same semaphore instance
    as every other caller of this graph, per `get_proposing_answerer_factory`."""
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
            propose_target="mock_data",
        )

    return answerer_for


MockDataDatasetServiceDep = Annotated[
    MockDataDatasetService, Depends(get_mock_data_dataset_service)
]
MockDataQueueDep = Annotated[MockDataQueue, Depends(get_mock_data_queue)]
ProposingMockDataAnswererFactoryDep = Annotated[
    AnswererFactory, Depends(get_proposing_mock_data_answerer_factory)
]


@router.get(
    "/{module_id}/mock-data",
    response_model=MockDataDatasetDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get a module's mock dataset and its records",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def get_mock_data_dataset(
    module_id: uuid.UUID, current_user: CurrentUser, service: MockDataDatasetServiceDep
) -> MockDataDatasetDetailResponse:
    """A module's dataset summary and its applied records."""
    return await service.get(module_id, actor=current_user)


@router.post(
    "/{module_id}/mock-data-generations",
    response_model=MockDataDatasetResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate mock data for this module",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def generate_mock_data(
    module_id: uuid.UUID,
    current_user: CurrentUser,
    service: MockDataDatasetServiceDep,
    queue: MockDataQueueDep,
    payload: MockDataGenerationRequest = DEFAULT_GENERATION_REQUEST,
) -> MockDataDatasetResponse:
    """Publish a generation job and return. The result is a change set to review."""
    return await service.request_generation(module_id, payload, actor=current_user, queue=queue)


@router.get(
    "/{module_id}/mock-data-change-sets",
    response_model=list[MockDataChangeSetResponse],
    status_code=status.HTTP_200_OK,
    summary="List a module's mock-data change sets",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def list_mock_data_change_sets(
    module_id: uuid.UUID, current_user: CurrentUser, service: MockDataDatasetServiceDep
) -> list[MockDataChangeSetResponse]:
    """Newest first: the audit trail of every proposal against this module's dataset."""
    return await service.change_sets_for(module_id, actor=current_user)


@router.get(
    "/{module_id}/mock-data-messages",
    response_model=list[MockDataMessageResponse],
    status_code=status.HTTP_200_OK,
    summary="Read a module's mock-data refinement chat",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def list_mock_data_messages(
    module_id: uuid.UUID, current_user: CurrentUser, service: MockDataDatasetServiceDep
) -> list[MockDataMessageResponse]:
    """Shared, like the checklist's own chat."""
    return await service.messages(module_id, actor=current_user)


@router.post(
    "/{module_id}/mock-data-messages",
    status_code=status.HTTP_200_OK,
    summary="Refine the mock dataset by chat, streaming the reply",
    response_class=StreamingResponse,
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def refine_mock_data(
    module_id: uuid.UUID,
    payload: MockDataMessageCreateRequest,
    current_user: CurrentUser,
    service: MockDataDatasetServiceDep,
    answerer_factory: ProposingMockDataAnswererFactoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Validate, persist the question, then stream the answer. Same pre-flight/stream
    split as `refine_checklist`, for the same reason."""
    context = await service.prepare_turn(module_id, payload, actor=current_user)
    return StreamingResponse(
        stream_mock_data_turn(
            context=context,
            answerer=answerer_factory(context.collection),
            sessionmaker=get_sessionmaker(),
            model_id=settings.chat_model,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.get(
    "/{module_id}/mock-data/export.json",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    summary="Export a module's mock data as JSON",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def export_mock_data_json(
    module_id: uuid.UUID, current_user: CurrentUser, service: MockDataDatasetServiceDep
) -> Response:
    content = await service.export_json(module_id, actor=current_user)
    return Response(
        content=content,
        media_type=JSON_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="mock-data.json"'},
    )


@router.get(
    "/{module_id}/mock-data/export.xlsx",
    response_class=Response,
    status_code=status.HTTP_200_OK,
    summary="Export a module's mock data as a spreadsheet",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def export_mock_data_xlsx(
    module_id: uuid.UUID, current_user: CurrentUser, service: MockDataDatasetServiceDep
) -> Response:
    content = await service.export_xlsx(module_id, actor=current_user)
    return Response(
        content=content,
        media_type=XLSX_MEDIA_TYPE,
        headers={"Content-Disposition": 'attachment; filename="mock-data.xlsx"'},
    )
