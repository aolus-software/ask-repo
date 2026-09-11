"""Small test helpers shared across suites."""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.middleware import AuthenticatedUser
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.user import User
from app.services.checklist_module import ChecklistModuleService
from app.services.indexed_path import IndexedPathCache, IndexedPathReader

DEFAULT_INDEXED_PATHS = (
    "app/auth/routes.py",
    "app/auth/service.py",
    "backend/app/api/routes/auth.py",
    "backend/app/api/routes/projects.py",
    "backend/app/core/access.py",
    "frontend/lib/nav.ts",
)
"""A stand-in repository tree, covering the paths the factories default to.

`create_checklist_module` points at `backend/app/api/routes` and the service tests
create against `app/auth`, so both have to be reachable or every module creation would
refuse with `MODULE_PATH_NOT_INDEXED`.
"""


def authenticated(user: User) -> AuthenticatedUser:
    """The frozen identity a service receives, built from a row.

    `AuthenticatedUser` is deliberately not the ORM `User`: the middleware resolves
    identity in its own session, which closes before the handler runs.
    """
    return AuthenticatedUser(
        id=user.id,
        name=user.name,
        email=user.email,
        is_admin=user.is_admin,
        must_change_password=user.must_change_password,
    )


class _FixedPathStore(InMemoryVectorStore):
    """A store whose path enumeration is fixed, whatever it holds.

    Subclasses the in-memory store rather than reimplementing the protocol, so it stays
    a whole `VectorStore` and needs no cast. A test about path *validation* should not
    have to seed points, embed vectors and pick a generation first -- a fake that needs
    all three to answer one question invites tests that skip the question.
    """

    def __init__(self, paths: tuple[str, ...]) -> None:
        super().__init__()
        self.paths = paths
        self.calls = 0

    async def list_file_paths(
        self, *, project_id: uuid.UUID, generation: int, page_size: int
    ) -> list[str]:
        """The fixed list, whatever project or generation was asked for."""
        self.calls += 1
        return sorted(self.paths)


def indexed_path_reader(
    *paths: str, settings: Settings | None = None
) -> tuple[IndexedPathReader, _FixedPathStore]:
    """A reader over a fixed path list, with a cache of its own.

    The cache is fresh per call rather than the process-wide one, so a test observes
    only the reads it made. Returns the store too, for tests that assert the cache
    stopped a second scroll.
    """
    resolved = settings or Settings()
    store = _FixedPathStore(paths or DEFAULT_INDEXED_PATHS)
    reader = IndexedPathReader(
        settings=resolved,
        store_factory=lambda collection: store,
        cache=IndexedPathCache(
            ttl_seconds=resolved.indexed_path_cache_ttl_seconds,
            max_entries=resolved.indexed_path_cache_max_projects,
        ),
    )
    return reader, store


def checklist_module_service(
    session: AsyncSession, *paths: str, settings: Settings | None = None
) -> ChecklistModuleService:
    """The service, wired to a reader that sees `paths` (or the default tree)."""
    resolved = settings or Settings()
    reader, _ = indexed_path_reader(*paths, settings=resolved)
    return ChecklistModuleService(session, resolved, indexed_paths=reader)


def seed_indexed_paths(
    store: InMemoryVectorStore,
    project_id: uuid.UUID,
    *paths: str,
    generation: int = 1,
) -> None:
    """Put one point per path into the fake store, so a route sees a real tree.

    For the tests that go through the app and therefore through the overridden
    `get_store_factory`, where the reader is the real one.
    """
    for index, file_path in enumerate(paths or DEFAULT_INDEXED_PATHS):
        store.points.append(
            {
                "id": str(uuid.uuid4()),
                "vector": [0.0] * store.dimensions,
                "payload": {
                    "project_id": str(project_id),
                    "generation": generation,
                    "file_path": file_path,
                    "start_line": 1,
                    "end_line": 2,
                    "language": "python",
                    "symbol": None,
                    "chunk_index": index,
                    "commit_sha": "abc123",
                    "content": "pass",
                },
            }
        )
