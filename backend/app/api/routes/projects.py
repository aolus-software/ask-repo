"""Project ingestion and lifecycle.

Reads are open to every authenticated user — `docs/PRD.md` §4.1 shares projects
instance-wide in phase 1. Destructive operations are gated inside the service, not
here, so `reindex` and `delete` cannot drift apart.
"""

import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query, Request, status

from app.api.deps import CurrentUser, SessionDep
from app.config import Settings, get_settings
from app.ingestion.vector_store import QdrantVectorStore, VectorStore
from app.queue.protocol import IngestionQueue
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ReindexResponse
from app.services.project import ProjectService, VectorStoreFactory

router = APIRouter(prefix="/projects", tags=["Projects"])


def get_ingestion_queue(request: Request) -> IngestionQueue:
    """The producer built during application startup.

    A dependency rather than a module global, so tests override it with the
    in-memory fake and never need a broker.
    """
    queue: IngestionQueue | None = getattr(request.app.state, "ingestion_queue", None)
    if queue is None:
        raise RuntimeError("ingestion queue is not configured; check the app lifespan")
    return queue


def build_store_factory(settings: Settings) -> VectorStoreFactory:
    """A way to reach whichever collection a project recorded its points in.

    No store is constructed here, and that is the point: the width a collection was
    created with is probed once at worker startup (spec §6.3), so a request handler
    has none to offer. Deleting a project builds a store for the collection named on
    its own row — and only then, so an unindexed project costs no Qdrant client at all.
    """

    def store_for(collection: str) -> VectorStore:
        return QdrantVectorStore(url=settings.qdrant_url, collection=collection)

    return store_for


def get_project_service(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[IngestionQueue, Depends(get_ingestion_queue)],
) -> ProjectService:
    """Provide the service with a request-scoped session."""
    return ProjectService(session, settings, queue, store_factory=build_store_factory(settings))


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]


@router.get(
    "",
    response_model=PaginatedResponse[ProjectResponse],
    status_code=status.HTTP_200_OK,
    summary="List all projects",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def list_projects(
    current_user: CurrentUser,
    service: ProjectServiceDep,
    query: Annotated[ListQuery, Query()],
) -> PaginatedResponse[ProjectResponse]:
    return await service.list(query, actor=current_user)


@router.get(
    "/{project_id}",
    response_model=ProjectResponse,
    status_code=status.HTTP_200_OK,
    summary="Get one project",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def get_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> ProjectResponse:
    return await service.get(project_id, actor=current_user)


@router.post(
    "",
    response_model=ProjectResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Create a project from a repository URL",
    responses={code: ERROR_RESPONSES[code] for code in (400, 401, 403, 422)},
)
async def create_project(
    payload: ProjectCreateRequest, current_user: CurrentUser, service: ProjectServiceDep
) -> ProjectResponse:
    return await service.create(payload, actor=current_user)


@router.post(
    "/{project_id}/reindex",
    response_model=ReindexResponse,
    status_code=status.HTTP_202_ACCEPTED,
    summary="Re-clone and re-index a project",
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422)},
)
async def reindex_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> ReindexResponse:
    return await service.reindex(project_id, actor=current_user)


@router.delete(
    "/{project_id}",
    status_code=status.HTTP_204_NO_CONTENT,
    summary="Delete a project and its index",
    # 503 is unique to this route: it is the only one that must reach Qdrant to
    # satisfy `docs/PRD.md` §5.1's same-operation hard delete.
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422, 503)},
)
async def delete_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> None:
    await service.delete(project_id, actor=current_user)
