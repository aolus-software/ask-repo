"""The shared QA List.

Access matches projects and inverts conversations: every authenticated user reads
every pair, and `created_by` gates editing and deleting rather than reading. Setting
the status is the one write open to everyone (`docs/PRD.md:338`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status
from fastapi.responses import StreamingResponse

from app.api.deps import CurrentUser, SessionDep
from app.api.routes.conversations import SSE_HEADERS, AnswererFactory, get_answerer_factory
from app.config import Settings, get_settings
from app.db.session import get_sessionmaker
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import PaginatedResponse
from app.schemas.qa_pair import (
    QAPairCreateRequest,
    QAPairDetailResponse,
    QAPairListQuery,
    QAPairResponse,
    QAPairStatusRequest,
    QAPairUpdateRequest,
)
from app.services.qa_pair import QAPairService, stream_rerun

router = APIRouter(prefix="/qa-pairs", tags=["QA List"])


def get_qa_pair_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> QAPairService:
    """Provide the service with a request-scoped session."""
    return QAPairService(session, settings)


QAPairServiceDep = Annotated[QAPairService, Depends(get_qa_pair_service)]
# Reused from the conversations router rather than rebuilt, which is what makes a
# re-run take the SAME instance-wide answer semaphore as the Ask screen. A separate
# factory here would give re-runs their own concurrency budget, and a burst of them
# could then starve someone asking a live question.
AnswererFactoryDep = Annotated[AnswererFactory, Depends(get_answerer_factory)]


@router.get(
    "",
    response_model=PaginatedResponse[QAPairResponse],
    status_code=status.HTTP_200_OK,
    summary="List saved QA pairs",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_qa_pairs(
    current_user: CurrentUser,
    service: QAPairServiceDep,
    query: Annotated[QAPairListQuery, Query()],
) -> PaginatedResponse[QAPairResponse]:
    """A page of pairs the caller may read."""
    return await service.list(query, actor=current_user)


# Declared BEFORE `/{pair_id}`. FastAPI matches in declaration order, so a literal
# path declared after a parameterised one is swallowed as an id.
@router.get(
    "/tags",
    response_model=list[str],
    status_code=status.HTTP_200_OK,
    summary="Every tag in use",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403)},
)
async def list_tags(current_user: CurrentUser, service: QAPairServiceDep) -> list[str]:
    """Distinct tags across the caller's scope, for the filter combobox."""
    return await service.tags(actor=current_user)


@router.get(
    "/{pair_id}",
    response_model=QAPairDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one QA pair",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404)},
)
async def get_qa_pair(
    pair_id: uuid.UUID, current_user: CurrentUser, service: QAPairServiceDep
) -> QAPairDetailResponse:
    """One pair, with its citations and any pending re-run."""
    return await service.get(pair_id, actor=current_user)


@router.post(
    "",
    response_model=QAPairDetailResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Save an answer to the QA List",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422)},
)
async def create_qa_pair(
    payload: QAPairCreateRequest, current_user: CurrentUser, service: QAPairServiceDep
) -> QAPairDetailResponse:
    """Publish a finished answer. The server copies it out of the message rows."""
    return await service.create(payload, actor=current_user)


@router.patch(
    "/{pair_id}",
    response_model=QAPairDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Edit a QA pair",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def update_qa_pair(
    pair_id: uuid.UUID,
    payload: QAPairUpdateRequest,
    current_user: CurrentUser,
    service: QAPairServiceDep,
) -> QAPairDetailResponse:
    """Edit module, question, expected result, or tags."""
    return await service.update(pair_id, payload, actor=current_user)


@router.put(
    "/{pair_id}/status",
    response_model=QAPairDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Set a QA pair's status",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def set_qa_pair_status(
    pair_id: uuid.UUID,
    payload: QAPairStatusRequest,
    current_user: CurrentUser,
    service: QAPairServiceDep,
) -> QAPairDetailResponse:
    """Record pass / fail / unreviewed. Open to every authenticated user."""
    return await service.set_status(pair_id, payload, actor=current_user)


@router.post(
    "/{pair_id}/rerun",
    status_code=status.HTTP_200_OK,
    summary="Re-run a saved question and stream the new answer",
    # No `response_model`: the body is `text/event-stream`, whose payload models
    # live in `app/schemas/conversation.py` and are checked by
    # `tests/test_api_model.py` rather than by FastAPI.
    response_class=StreamingResponse,
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409)},
)
async def rerun_qa_pair(
    pair_id: uuid.UUID,
    current_user: CurrentUser,
    service: QAPairServiceDep,
    answerer_factory: AnswererFactoryDep,
    settings: Annotated[Settings, Depends(get_settings)],
) -> Response:
    """Validate, then stream. The second route in the codebase that does two things.

    Once the response body has started there is no status code left to set, so
    every decision that needs one happens in `prepare_rerun` first. All of the
    policy is still in the service — the route only chooses the transport.
    """
    context = await service.prepare_rerun(pair_id, actor=current_user)
    return StreamingResponse(
        stream_rerun(
            context=context,
            answerer=answerer_factory(context.collection),
            sessionmaker=get_sessionmaker(),
            model_id=settings.chat_model,
        ),
        media_type="text/event-stream",
        headers=SSE_HEADERS,
    )


@router.post(
    "/{pair_id}/rerun/accept",
    response_model=QAPairDetailResponse,
    status_code=status.HTTP_200_OK,
    summary="Save a pending re-run over the stored answer",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409)},
)
async def accept_rerun(
    pair_id: uuid.UUID, current_user: CurrentUser, service: QAPairServiceDep
) -> QAPairDetailResponse:
    """Promote the pending run. The status resets to unreviewed."""
    return await service.accept_rerun(pair_id, actor=current_user)


@router.delete(
    "/{pair_id}/rerun",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Discard a pending re-run",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409)},
)
async def discard_rerun(
    pair_id: uuid.UUID, current_user: CurrentUser, service: QAPairServiceDep
) -> Response:
    """Throw the pending run away, leaving the stored answer alone."""
    await service.discard_rerun(pair_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.delete(
    "/{pair_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a QA pair",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404)},
)
async def delete_qa_pair(
    pair_id: uuid.UUID, current_user: CurrentUser, service: QAPairServiceDep
) -> Response:
    """Soft-delete a pair."""
    await service.delete(pair_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
