"""Project lifecycle: create, list, read, reindex, delete.

The `created_by`-or-admin gate lives here rather than in the routes, so `reindex`
and `delete` cannot drift apart (`.claude/rules/router.md`).
"""

import logging
import uuid
from collections.abc import Callable
from urllib.parse import urlsplit

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.crypto import SecretBox
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.core.repo_url import RepoUrlRejected, validate_repo_url
from app.ingestion.errors import IngestionError
from app.ingestion.vector_store import VectorStore
from app.models.project import Project, ProjectStatus
from app.queue.protocol import IngestionQueue
from app.queue.topics import INGEST_TOPIC, IngestionMessage
from app.repositories.project import ProjectRepository
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.project import ProjectCreateRequest, ProjectResponse, ReindexResponse

logger = logging.getLogger(__name__)

DEFAULT_SORT = "created_at"

VectorStoreFactory = Callable[[str], VectorStore]
"""Collection name in, a store for that collection out.

A factory rather than one pre-built store, because the only honest source of a
collection's vector width is the startup probe (spec §6.3) and a request handler has
no probed width to build a store with. Deleting a project therefore has to target the
collection the project itself recorded, which is only known once its row is loaded.
"""

# A run is in flight in these states, so a second trigger is a no-op.
BUSY_STATUSES = frozenset(
    {ProjectStatus.PENDING.value, ProjectStatus.CLONING.value, ProjectStatus.INDEXING.value}
)


class ProjectService:
    """Business rules for projects. Owns its transactions."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        queue: IngestionQueue,
        *,
        store_factory: VectorStoreFactory,
    ) -> None:
        self.session = session
        self.settings = settings
        self.queue = queue
        self.store_factory = store_factory
        self._repository = ProjectRepository(session)

    async def create(
        self, payload: ProjectCreateRequest, *, actor: AuthenticatedUser
    ) -> ProjectResponse:
        """Record a project and enqueue its first indexing run.

        Any authenticated user may create one (`docs/PRD.md` §4.1, confirmed in the
        spec's §2.3). Validation runs before the row is written, so a rejected URL
        leaves nothing behind.
        """
        try:
            await validate_repo_url(payload.repo_url, allowlist=self.settings.repo_host_allowlist)
        except RepoUrlRejected as rejected:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_REPO_URL, rejected.reason
            ) from rejected

        encrypted_pat = None
        if payload.pat:
            encrypted_pat = SecretBox(self.settings.pat_encryption_key).encrypt(payload.pat)

        project = Project(
            id=uuid.uuid4(),
            created_by=actor.id,
            name=_derive_name(payload.repo_url),
            repo_url=payload.repo_url,
            branch=payload.branch,
            status=ProjectStatus.PENDING.value,
            encrypted_pat=encrypted_pat,
        )
        await self._repository.add(project)
        await self.session.commit()

        # Produced after the commit: a message referencing an uncommitted row would
        # race the worker. The reconcile sweep covers a produce that fails here.
        await self._enqueue(project.id)
        return ProjectResponse.model_validate(project)

    async def list(
        self, query: ListQuery, *, actor: AuthenticatedUser
    ) -> PaginatedResponse[ProjectResponse]:
        """A page of projects the caller may read.

        The scope comes from the access resolver and nowhere else. In phase 1 it is
        unrestricted; phase 2 changes the resolver's body and this line stays put.
        """
        scope = access.resolve_project_scope(actor)
        try:
            rows, total = await self._repository.list_page(
                scope=scope,
                page=query.page,
                limit=query.limit,
                search=query.search,
                sort=query.sort or DEFAULT_SORT,
                descending=query.sort_direction == "desc",
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.INVALID_SORT_FIELD, str(error)
            ) from error

        return PaginatedResponse.build(
            [ProjectResponse.model_validate(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get(self, project_id: uuid.UUID, *, actor: AuthenticatedUser) -> ProjectResponse:
        """One project, by id."""
        return ProjectResponse.model_validate(await self._require_readable(project_id, actor))

    async def reindex(self, project_id: uuid.UUID, *, actor: AuthenticatedUser) -> ReindexResponse:
        """Trigger a fresh indexing run. Idempotent while one is already in flight.

        The busy check here is a fast path, **not** a correctness boundary: two
        simultaneous callers both pass it and both enqueue. The worker's lease claim
        settles that (`ProjectRepository.claim`). Do not delete the lease on the
        grounds that this check exists.
        """
        project = await self._require_readable(project_id, actor)
        self._require_destructive_rights(project, actor)

        if project.status in BUSY_STATUSES or project.reindex_in_progress:
            return ReindexResponse(enqueued=False, project=ProjectResponse.model_validate(project))

        await self._enqueue(project.id)
        return ReindexResponse(enqueued=True, project=ProjectResponse.model_validate(project))

    async def delete(self, project_id: uuid.UUID, *, actor: AuthenticatedUser) -> None:
        """Soft-delete the project and hard-delete its vectors, in one operation.

        `docs/PRD.md` §5.1: vector points carry no `deleted_at`, so a query-time
        filter would be one forgotten call away from serving deleted content. The
        points go for real, in the collection the project recorded — not in whichever
        collection is currently active, which a later provider switch would have
        moved on from (spec §6.4).

        A project that was never indexed has no collection and no points, so Qdrant is
        not called at all. The vector delete runs before the commit deliberately: if
        Qdrant refuses, the row stays visible rather than becoming a soft-deleted
        project whose content is still queryable.
        """
        project = await self._require_readable(project_id, actor)
        self._require_destructive_rights(project, actor)
        await self._repository.soft_delete(project)

        if project.embedding_collection:
            store = self.store_factory(project.embedding_collection)
            try:
                await store.delete_project(project.id)
            except IngestionError as error:
                # Not a bug, so not a 500 (`.claude/rules/response-api.md`): the vector
                # store is a dependency and it is down. Nothing is committed, so the
                # project stays visible and the caller can retry.
                logger.exception(
                    "Vector delete failed for project %s in collection %s",
                    project.id,
                    project.embedding_collection,
                )
                raise AppError(
                    status.HTTP_503_SERVICE_UNAVAILABLE,
                    ErrorCode.VECTOR_STORE_UNAVAILABLE,
                    "The vector store is unreachable, so the project was not deleted.",
                ) from error

        await self.session.commit()

    async def _enqueue(self, project_id: uuid.UUID) -> None:
        """Publish one job for this project."""
        await self.queue.enqueue(
            IngestionMessage(
                project_id=project_id,
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=0,
                original_topic=INGEST_TOPIC,
            )
        )

    async def _require_readable(self, project_id: uuid.UUID, actor: AuthenticatedUser) -> Project:
        """Load a project the caller may see, or raise 404."""
        scope = access.resolve_project_scope(actor)
        project = await self._repository.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    def _require_destructive_rights(self, project: Project, actor: AuthenticatedUser) -> None:
        """Delete and reindex need `created_by` or admin (`docs/PRD.md` §4.1).

        403 rather than 404: project existence is deliberately public here, so
        hiding it would only confuse.
        """
        if actor.is_admin or project.created_by == actor.id:
            return
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.NOT_PROJECT_OWNER,
            "Only the person who added this project, or an administrator, can do that.",
        )


def _derive_name(repo_url: str) -> str:
    """A display name from the URL's last path segment, minus any `.git`."""
    segment = urlsplit(repo_url).path.rstrip("/").rsplit("/", 1)[-1]
    return segment.removesuffix(".git") or "project"
