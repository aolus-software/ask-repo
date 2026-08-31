"""The shared QA List.

Access matches projects and inverts conversations: every authenticated user reads
every pair, and `created_by` gates editing and deleting rather than reading. Setting
the status is the one write open to everyone (`docs/PRD.md:338`).
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Response, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
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
from app.services.qa_pair import QAPairService

router = APIRouter(prefix="/qa-pairs", tags=["QA List"])


def get_qa_pair_service(
    session: SessionDep, settings: Annotated[Settings, Depends(get_settings)]
) -> QAPairService:
    """Provide the service with a request-scoped session."""
    return QAPairService(session, settings)


QAPairServiceDep = Annotated[QAPairService, Depends(get_qa_pair_service)]


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
