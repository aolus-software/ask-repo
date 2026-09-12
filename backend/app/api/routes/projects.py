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
from app.ingestion.vector_store import VectorStoreFactory, build_store_factory
from app.queue.protocol import IngestionQueue
from app.schemas.errors import ERROR_RESPONSES
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.project import (
    IndexedPathsResponse,
    ProjectCreateRequest,
    ProjectResponse,
    ReindexResponse,
)
from app.services.indexed_path import IndexedPathReader, IndexedPathService, shared_cache
from app.services.project import ProjectService

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


def get_store_factory(
    settings: Annotated[Settings, Depends(get_settings)],
) -> VectorStoreFactory:
    """How this process reaches a project's Qdrant collection.

    A dependency rather than a direct call, for the same reason the queue is one: it is
    the seam a test overrides so that reaching Qdrant needs no Qdrant. Two routes talk
    to the vector store -- `DELETE /projects/{id}` and the path picker's
    `indexed-paths` -- and without this every route test exercising either opens a real
    connection.
    """
    return build_store_factory(settings)


def get_project_service(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    queue: Annotated[IngestionQueue, Depends(get_ingestion_queue)],
    store_factory: Annotated[VectorStoreFactory, Depends(get_store_factory)],
) -> ProjectService:
    """Provide the service with a request-scoped session."""
    return ProjectService(session, settings, queue, store_factory=store_factory)


def get_indexed_path_reader(
    settings: Annotated[Settings, Depends(get_settings)],
    store_factory: Annotated[VectorStoreFactory, Depends(get_store_factory)],
) -> IndexedPathReader:
    """The project's indexed file paths, cached per (project, generation).

    Declared here beside `get_store_factory` because that is what it needs, and
    imported by `checklist_modules.py`: the same reader answers the path picker's
    browse requests and refuses a `source_path` that matches nothing at creation, and
    two readers would mean two caches disagreeing about the same repository.
    """
    return IndexedPathReader(
        settings=settings, store_factory=store_factory, cache=shared_cache(settings)
    )


def get_indexed_path_service(
    session: SessionDep,
    settings: Annotated[Settings, Depends(get_settings)],
    reader: Annotated[IndexedPathReader, Depends(get_indexed_path_reader)],
) -> IndexedPathService:
    """Provide the service with a request-scoped session."""
    return IndexedPathService(session, settings, reader=reader)


ProjectServiceDep = Annotated[ProjectService, Depends(get_project_service)]
IndexedPathServiceDep = Annotated[IndexedPathService, Depends(get_indexed_path_service)]


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


@router.get(
    "/{project_id}/indexed-paths",
    response_model=IndexedPathsResponse,
    status_code=status.HTTP_200_OK,
    summary="Browse or search a project's indexed file tree",
    # `409` when the project has no index to enumerate, and `503` for the same reason
    # the delete route declares it: this read reaches Qdrant.
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 409, 422, 503)},
)
async def list_indexed_paths(
    project_id: uuid.UUID,
    current_user: CurrentUser,
    service: IndexedPathServiceDep,
    path: Annotated[str, Query(max_length=1024)] = "",
    search: Annotated[str | None, Query(max_length=1024)] = None,
) -> IndexedPathsResponse:
    """One directory's children, or every match for `search` across the whole tree.

    Two scalar query params rather than a query model on purpose: FastAPI only
    flattens a Pydantic model into individual params while it is a route's *sole*
    query parameter (`.claude/rules/rag.md`), and this route needs two.
    """
    return await service.list_entries(project_id, path=path, search=search, actor=current_user)


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
    # 503 because this route must reach Qdrant to satisfy `docs/PRD.md` §5.1's
    # same-operation hard delete. `indexed-paths` above is the only other route here
    # that talks to the vector store, and declares it for the same reason.
    responses={code: ERROR_RESPONSES[code] for code in (401, 403, 404, 422, 503)},
)
async def delete_project(
    project_id: uuid.UUID, current_user: CurrentUser, service: ProjectServiceDep
) -> None:
    await service.delete(project_id, actor=current_user)
