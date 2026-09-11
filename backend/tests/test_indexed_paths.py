"""The indexed-path read: the cache, the reader, and the browse route (phase 1.1).

The cache is the part that fails silently when it is wrong. A key that did not carry the
generation would serve a reindexed project its old tree with nothing reporting an error,
so that is asserted directly rather than inferred from a passing browse.
"""

import uuid

import pytest
from fastapi import status
from httpx import AsyncClient
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.ingestion.errors import RetryableIngestionError
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import Project, ProjectStatus
from app.services.indexed_path import IndexedPathCache, IndexedPathReader
from tests.factories import create_project
from tests.helpers import indexed_path_reader, seed_indexed_paths

TREE = ("backend/app/api/routes/auth.py", "backend/app/config.py", "frontend/lib/nav.ts")


async def _indexed_project(session: AsyncSession, *, generation: int = 1) -> Project:
    project = await create_project(session, status=ProjectStatus.READY)
    project.embedding_collection = "code_chunks__ollama__nomic_embed_text__768"
    project.embedding_model = Settings().embedding_model
    project.active_generation = generation
    await session.flush()
    return project


def _cache() -> IndexedPathCache:
    return IndexedPathCache(ttl_seconds=300, max_entries=2)


# --- the cache -------------------------------------------------------------------


def test_the_cache_keys_on_the_generation_so_a_reindex_cannot_be_served_stale() -> None:
    """A generation swap writes N+1 while N still serves, then flips the pointer. If the
    key were the project alone, the swap would hand out the superseded tree and nothing
    anywhere would report it."""
    cache = _cache()
    project_id = uuid.uuid4()
    cache.put(project_id, 1, ("old.py",))

    assert cache.get(project_id, 1) == ("old.py",)
    assert cache.get(project_id, 2) is None


def test_the_cache_expires_an_entry_past_its_ttl() -> None:
    """The TTL covers what the generation key cannot see: points rewritten within one
    generation by a retried indexing batch."""
    cache = IndexedPathCache(ttl_seconds=1, max_entries=2)
    project_id = uuid.uuid4()
    cache.put(project_id, 1, ("a.py",))
    # Reach past the clock rather than sleeping: the assertion is about the TTL
    # comparison, and a real second of wall time buys nothing.
    stale = cache._entries[project_id, 1]
    cache._entries[project_id, 1] = type(stale)(paths=stale.paths, stored_at=stale.stored_at - 10)

    assert cache.get(project_id, 1) is None


def test_the_cache_evicts_the_least_recently_used_entry() -> None:
    cache = _cache()
    first, second, third = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    cache.put(first, 1, ("a",))
    cache.put(second, 1, ("b",))
    cache.get(first, 1)  # first is now the most recently used of the two
    cache.put(third, 1, ("c",))

    assert cache.get(second, 1) is None
    assert cache.get(first, 1) == ("a",)


# --- the reader ------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_reader_scrolls_once_and_serves_the_rest_from_the_cache(
    db_session: AsyncSession,
) -> None:
    project = await _indexed_project(db_session)
    reader, store = indexed_path_reader(*TREE)

    first = await reader.paths_for(project)
    second = await reader.paths_for(project)

    assert first == second == tuple(sorted(TREE))
    assert store.calls == 1


@pytest.mark.asyncio
async def test_the_reader_scrolls_again_after_the_generation_moves(
    db_session: AsyncSession,
) -> None:
    project = await _indexed_project(db_session)
    reader, store = indexed_path_reader(*TREE)

    await reader.paths_for(project)
    project.active_generation = 2
    await reader.paths_for(project)

    assert store.calls == 2


@pytest.mark.asyncio
async def test_an_unreachable_vector_store_is_503_not_500(db_session: AsyncSession) -> None:
    """Someone else's outage, and the request can be retried unchanged
    (`.claude/rules/response-api.md`)."""

    class _BrokenStore(InMemoryVectorStore):
        async def list_file_paths(
            self, *, project_id: uuid.UUID, generation: int, page_size: int
        ) -> list[str]:
            raise RetryableIngestionError("qdrant is down")

    project = await _indexed_project(db_session)
    reader = IndexedPathReader(
        settings=Settings(), store_factory=lambda collection: _BrokenStore(), cache=_cache()
    )

    with pytest.raises(AppError) as caught:
        await reader.paths_for(project)

    assert caught.value.status_code == status.HTTP_503_SERVICE_UNAVAILABLE
    assert caught.value.code is ErrorCode.VECTOR_STORE_UNAVAILABLE


# --- the route -------------------------------------------------------------------


@pytest.mark.asyncio
async def test_browsing_the_root_returns_one_level_in_camel_case(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    project = await _indexed_project(db_session)
    seed_indexed_paths(vector_store, project.id, *TREE)
    await db_session.commit()

    response = await authed_client.get(f"/projects/{project.id}/indexed-paths")

    assert response.status_code == status.HTTP_200_OK
    body = response.json()
    assert body["path"] == ""
    assert body["generation"] == 1
    assert body["truncated"] is False
    assert [(entry["name"], entry["kind"]) for entry in body["entries"]] == [
        ("backend", "dir"),
        ("frontend", "dir"),
    ]
    # `fileCount`, not `file_count`: every JSON body is camelCase (`ApiModel`).
    assert body["entries"][0]["fileCount"] == 2


@pytest.mark.asyncio
async def test_browsing_a_directory_takes_a_path_and_tolerates_slashes(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    project = await _indexed_project(db_session)
    seed_indexed_paths(vector_store, project.id, *TREE)
    await db_session.commit()

    response = await authed_client.get(
        f"/projects/{project.id}/indexed-paths", params={"path": "/backend/app/"}
    )

    body = response.json()
    assert body["path"] == "backend/app"
    assert [entry["path"] for entry in body["entries"]] == [
        "backend/app/api",
        "backend/app/config.py",
    ]


@pytest.mark.asyncio
async def test_searching_spans_the_tree_and_reports_no_directory(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """`path` comes back empty on a search: the results span the tree, so echoing the
    directory the client was looking at would misdescribe them."""
    project = await _indexed_project(db_session)
    seed_indexed_paths(vector_store, project.id, *TREE)
    await db_session.commit()

    response = await authed_client.get(
        f"/projects/{project.id}/indexed-paths", params={"path": "backend", "search": "nav"}
    )

    body = response.json()
    assert body["path"] == ""
    assert [entry["path"] for entry in body["entries"]] == ["frontend/lib/nav.ts"]


@pytest.mark.asyncio
async def test_browsing_an_unindexed_project_is_409(
    authed_client: AsyncClient, db_session: AsyncSession
) -> None:
    """`409`, not an empty list: a picker showing no files is indistinguishable from a
    repository that has none, and the user would go looking for the wrong problem."""
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    await db_session.commit()

    response = await authed_client.get(f"/projects/{project.id}/indexed-paths")

    assert response.status_code == status.HTTP_409_CONFLICT
    assert response.json()["detail"]["code"] == "PROJECT_NOT_READY"


@pytest.mark.asyncio
async def test_browsing_an_unknown_project_is_404(authed_client: AsyncClient) -> None:
    response = await authed_client.get(f"/projects/{uuid.uuid4()}/indexed-paths")

    assert response.status_code == status.HTTP_404_NOT_FOUND
    assert response.json()["detail"]["code"] == "PROJECT_NOT_FOUND"


@pytest.mark.asyncio
async def test_browsing_needs_authentication(client: AsyncClient) -> None:
    response = await client.get(f"/projects/{uuid.uuid4()}/indexed-paths")

    assert response.status_code == status.HTTP_401_UNAUTHORIZED


@pytest.mark.asyncio
async def test_a_reindex_in_flight_does_not_block_browsing(
    authed_client: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """The live generation is still serving throughout a reindex and this read records
    nothing, so it takes the readiness check and not the stability check -- the same
    split the question and chat paths make (`.claude/rules/ingestion.md`)."""
    project = await _indexed_project(db_session)
    project.reindex_in_progress = True
    seed_indexed_paths(vector_store, project.id, *TREE)
    await db_session.commit()

    response = await authed_client.get(f"/projects/{project.id}/indexed-paths")

    assert response.status_code == status.HTTP_200_OK


@pytest.mark.asyncio
async def test_another_users_project_tree_is_readable_because_phase_1_shares_projects(
    client_for_user_b: AsyncClient, db_session: AsyncSession, vector_store: InMemoryVectorStore
) -> None:
    """Intended, not a leak (`docs/PRD.md` §4.1): the read scopes through the access
    resolver, which returns everything in phase 1."""
    project = await _indexed_project(db_session)
    seed_indexed_paths(vector_store, project.id, *TREE)
    await db_session.commit()

    response = await client_for_user_b.get(f"/projects/{project.id}/indexed-paths")

    assert response.status_code == status.HTTP_200_OK
