"""Eval sets: generate, list, read, delete, and exclude a pair.

Access is a project membership with `eval.read` / `eval.run` (`app/core/access.py`); a
set and a pair have no scope of their own and resolve through their project.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, Response, status

from app.api.deps import AuditRecorderDep, CurrentUser, SessionDep
from app.api.routes.projects import get_indexed_path_reader
from app.config import Settings, get_settings
from app.queue.protocol import EvalQueue
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.eval import (
    EvalPairExclude,
    EvalPairRead,
    EvalSetCreate,
    EvalSetDetail,
    EvalSetSummary,
)
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.services.eval import EvalService
from app.services.indexed_path import IndexedPathReader

project_router = APIRouter(prefix="/projects", tags=["Eval"])
router = APIRouter(tags=["Eval"])


def get_eval_service(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    indexed_paths: Annotated[IndexedPathReader, Depends(get_indexed_path_reader)],
    recorder: AuditRecorderDep,
) -> EvalService:
    """Provide the service with a request-scoped session."""
    return EvalService(session, settings, indexed_paths=indexed_paths, recorder=recorder)


def get_eval_queue(request: Request) -> EvalQueue:
    """The Kafka producer built during startup, narrowed to the eval half of its surface."""
    queue: EvalQueue | None = getattr(request.app.state, "ingestion_queue", None)
    if queue is None:
        raise RuntimeError("the job queue is not configured; check the app lifespan")
    return queue


EvalServiceDep = Annotated[EvalService, Depends(get_eval_service)]
EvalQueueDep = Annotated[EvalQueue, Depends(get_eval_queue)]


@project_router.post(
    "/{project_id}/eval-sets",
    response_model=EvalSetSummary,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Generate an eval set",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 404, 409, 422)},
)
async def create_eval_set(
    project_id: uuid.UUID,
    payload: EvalSetCreate,
    current_user: CurrentUser,
    service: EvalServiceDep,
    queue: EvalQueueDep,
) -> EvalSetSummary:
    """Publish a generation job and return the `generating` set."""
    return await service.create_set(project_id, payload, actor=current_user, queue=queue)


@project_router.get(
    "/{project_id}/eval-sets",
    response_model=PaginatedResponse[EvalSetSummary],
    status_code=status.HTTP_200_OK,
    summary="List a project's eval sets",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def list_eval_sets(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    service: EvalServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[EvalSetSummary]:
    """A page of sets, newest first, each with its latest run."""
    return await service.list_sets(project_id, query, actor=current_user)


@router.get(
    "/eval-sets/{set_id}",
    response_model=EvalSetDetail,
    status_code=status.HTTP_200_OK,
    summary="Get one eval set and its pairs",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404)},
)
async def get_eval_set(
    set_id: uuid.UUID, current_user: CurrentUser, service: EvalServiceDep
) -> EvalSetDetail:
    """One set with every pair in order, excluded ones flagged."""
    return await service.get_set(set_id, actor=current_user)


@router.delete(
    "/eval-sets/{set_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete an eval set",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409)},
)
async def delete_eval_set(
    set_id: uuid.UUID, current_user: CurrentUser, service: EvalServiceDep
) -> Response:
    """Soft-delete the set, its pairs, its runs and their results."""
    await service.delete_set(set_id, actor=current_user)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put(
    "/eval-pairs/{pair_id}/excluded",
    response_model=EvalPairRead,
    status_code=status.HTTP_200_OK,
    summary="Exclude a pair from future runs, or include it again",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def set_pair_excluded(
    pair_id: uuid.UUID,
    payload: EvalPairExclude,
    current_user: CurrentUser,
    service: EvalServiceDep,
) -> EvalPairRead:
    """Idempotent: setting the state a pair already has writes and audits nothing."""
    return await service.set_excluded(pair_id, payload, actor=current_user)
