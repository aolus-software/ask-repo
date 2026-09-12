"""Reading a project's indexed file paths, so a path can be picked instead of typed.

`docs/PRD.md` §2.1 (phase 1.1) makes this the friendlier alternative to a free-typed
`source_path` on a checklist module. Three things about it are load-bearing:

1. **The read is an enumeration, not a search.** No query vector and no chat model --
   `VectorStore.list_file_paths` asks Qdrant for the `file_path` payload and nothing
   else. Because nothing here embeds anything, the `EMBEDDING_MODEL_CHANGED` guard
   does not apply, for the same reason it does not apply to generation.
2. **The wire shape is one directory at a time; the cache holds the whole list.** That
   is not a contradiction: Qdrant has no notion of a directory, so reading the children
   of one path costs a prefix filter over the same collection as reading all of them.
   One scroll per picker session, sliced in memory, is strictly less work than one per
   expand -- while the lazy responses stay small on a repository of thousands of files.
3. **The cache key carries the generation, so a reindex cannot be served a stale list.**
   A generation swap increments `active_generation` (`.claude/rules/ingestion.md`), and
   the key the new generation needs does not exist yet. The TTL covers only what the key
   cannot see -- points rewritten within one generation by a retried batch -- and keeps a
   bounded cache from pinning memory for a project nobody has opened in an hour.

Read scoping goes through `access.resolve_project_scope` and nothing else.
"""

import logging
import time
import uuid
from collections import OrderedDict
from dataclasses import dataclass

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core import access
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.ingestion.errors import IngestionError
from app.ingestion.vector_store import VectorStoreFactory
from app.models.project import Project, ProjectStatus
from app.repositories.project import ProjectRepository
from app.schemas.project import IndexedPathEntry, IndexedPathsResponse
from app.services import path_tree

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class _CacheEntry:
    paths: tuple[str, ...]
    stored_at: float


class IndexedPathCache:
    """Path lists keyed by `(project_id, generation)`, bounded by count and by age.

    In-process rather than in Redis, on two grounds. `CLAUDE.md` records that Redis is
    read by the login rate limiter and by nothing else, and a derived list that one
    scroll rebuilds is a poor first reason to make that false. And the deployment
    premise is one organization on one box (`docs/PRD.md` §2), so a second process
    rebuilding its own copy costs one scroll, not correctness.

    Eviction is least-recently-used: a picker session hits the same key repeatedly while
    the user browses, so recency is a better predictor here than insertion order.
    """

    def __init__(self, *, ttl_seconds: int, max_entries: int) -> None:
        self._ttl = float(ttl_seconds)
        self._max_entries = max_entries
        self._entries: OrderedDict[tuple[uuid.UUID, int], _CacheEntry] = OrderedDict()

    def get(self, project_id: uuid.UUID, generation: int) -> tuple[str, ...] | None:
        """The cached list, or `None` when it is absent or past its TTL."""
        key = (project_id, generation)
        entry = self._entries.get(key)
        if entry is None:
            return None
        if time.monotonic() - entry.stored_at > self._ttl:
            del self._entries[key]
            return None
        self._entries.move_to_end(key)
        return entry.paths

    def put(self, project_id: uuid.UUID, generation: int, paths: tuple[str, ...]) -> None:
        """Store a list, evicting the least recently used one if the cache is full."""
        key = (project_id, generation)
        self._entries[key] = _CacheEntry(paths=paths, stored_at=time.monotonic())
        self._entries.move_to_end(key)
        while len(self._entries) > self._max_entries:
            self._entries.popitem(last=False)


class IndexedPathReader:
    """A project's indexed file paths, from the cache or from one Qdrant scroll.

    Split from `IndexedPathService` because two callers need the paths and only one of
    them is answering a browse request: `ChecklistModuleService` uses this to refuse a
    `source_path` that matches nothing, at creation rather than at generation time.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        store_factory: VectorStoreFactory,
        cache: IndexedPathCache,
    ) -> None:
        self.settings = settings
        self.store_factory = store_factory
        self.cache = cache

    async def paths_for(self, project: Project) -> tuple[str, ...]:
        """Every indexed file path in this project's active generation, sorted.

        The collection comes from `project.embedding_collection` verbatim, never
        recomputed from current settings: the vector width is probed at worker startup
        and is not available in this process, and a project indexed before a provider
        switch legitimately lives in a collection current settings would not name
        (`.claude/rules/rag.md`).
        """
        collection = project.embedding_collection
        if not collection:
            return ()
        cached = self.cache.get(project.id, project.active_generation)
        if cached is not None:
            return cached

        store = self.store_factory(collection)
        try:
            paths = await store.list_file_paths(
                project_id=project.id,
                generation=project.active_generation,
                page_size=self.settings.indexed_path_scroll_page_size,
            )
        except IngestionError as error:
            # A dependency is down, not a bug: `503`, not `500`
            # (`.claude/rules/response-api.md`). Nothing was written, so the caller can
            # retry the request unchanged.
            logger.exception(
                "Path enumeration failed for project %s in collection %s",
                project.id,
                collection,
            )
            raise AppError(
                status.HTTP_503_SERVICE_UNAVAILABLE,
                ErrorCode.VECTOR_STORE_UNAVAILABLE,
                "The vector store is unreachable, so the repository tree could not be read.",
            ) from error

        resolved = tuple(paths)
        self.cache.put(project.id, project.active_generation, resolved)
        return resolved


class IndexedPathService:
    """The browse request: resolve access, load the paths, shape one level of tree."""

    def __init__(
        self, session: AsyncSession, settings: Settings, *, reader: IndexedPathReader
    ) -> None:
        self.settings = settings
        self.reader = reader
        self.projects = ProjectRepository(session)

    async def list_entries(
        self, project_id: uuid.UUID, *, path: str, search: str | None, actor: AuthenticatedUser
    ) -> IndexedPathsResponse:
        """One directory's children, or the whole-tree matches for `search`.

        A reindex in flight is deliberately not refused. The live generation is still
        serving throughout one, and this read records nothing -- so it takes the
        readiness check and not the stability check, the same split the question and
        chat paths make (`.claude/rules/ingestion.md`).
        """
        project = await self._require_readable(project_id, actor)
        self._require_indexed(project)
        paths = await self.reader.paths_for(project)

        if search:
            entries, truncated = path_tree.matching(
                paths, search, limit=self.settings.indexed_path_search_limit
            )
            # `path` is empty on a search: the results span the tree, so echoing back
            # the directory the client happened to be looking at would misdescribe them.
            return _response(
                path="",
                generation=project.active_generation,
                entries=entries,
                truncated=truncated,
            )

        directory = path.strip().strip("/")
        return _response(
            path=directory,
            generation=project.active_generation,
            entries=path_tree.children_of(paths, directory),
            truncated=False,
        )

    async def _require_readable(self, project_id: uuid.UUID, actor: AuthenticatedUser) -> Project:
        """The project, if the access resolver returns it. A miss is `404`."""
        scope = access.resolve_project_scope(actor)
        project = await self.projects.get(project_id)
        if project is None or not (scope.unrestricted or project.id in scope.ids):
            raise AppError(
                status.HTTP_404_NOT_FOUND, ErrorCode.PROJECT_NOT_FOUND, "Project not found."
            )
        return project

    @staticmethod
    def _require_indexed(project: Project) -> None:
        """There has to be an index to enumerate.

        `409` rather than an empty list: a picker showing no files is indistinguishable
        from a repository that has none, and the user would go looking for the wrong
        problem.
        """
        if project.status != ProjectStatus.READY.value or not project.embedding_collection:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PROJECT_NOT_READY,
                "This project is not indexed yet. Wait for indexing to finish.",
            )


def _response(
    *, path: str, generation: int, entries: list[path_tree.PathEntry], truncated: bool
) -> IndexedPathsResponse:
    """Map the tree dataclasses onto the wire models."""
    return IndexedPathsResponse(
        path=path,
        generation=generation,
        entries=[
            IndexedPathEntry(
                name=entry.name,
                path=entry.path,
                kind="dir" if entry.is_directory else "file",
                file_count=entry.file_count,
            )
            for entry in entries
        ],
        truncated=truncated,
    )


_SHARED: dict[str, IndexedPathCache] = {}
_SHARED_KEY = "cache"


def shared_cache(settings: Settings) -> IndexedPathCache:
    """The process-wide cache the route dependency injects.

    Built once and shared, because a cache constructed per request would never hit --
    and holding it here rather than inside `IndexedPathReader` is what lets a test pass
    a fresh `IndexedPathCache` and observe the reader with no shared state at all.

    Held in a dict rather than a rebound module global so `reset_shared_cache` does not
    need `global`, and so every reader built during one process sees the same object.
    """
    cache = _SHARED.get(_SHARED_KEY)
    if cache is None:
        cache = IndexedPathCache(
            ttl_seconds=settings.indexed_path_cache_ttl_seconds,
            max_entries=settings.indexed_path_cache_max_projects,
        )
        _SHARED[_SHARED_KEY] = cache
    return cache


def reset_shared_cache() -> None:
    """Drop the process-wide cache. For tests, and for nothing else.

    Without it one test's path list outlives its project and answers the next test that
    reuses the id -- and a cache leaking across tests hides exactly the staleness the
    generation-keyed design exists to make impossible.
    """
    _SHARED.clear()
