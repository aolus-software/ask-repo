"""Project lifecycle rules: the destructive gate, the idempotent reindex, and the
fact that a PAT never leaves the service."""

import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthenticatedUser
from app.ingestion.chunker import Chunk
from app.ingestion.vector_store import InMemoryVectorStore, VectorStore
from app.models.project import ProjectStatus
from app.queue.protocol import InMemoryIngestionQueue
from app.repositories.project import ProjectRepository
from app.schemas.project import ProjectCreateRequest
from app.services.project import ProjectService, VectorStoreFactory
from tests.factories import create_project, create_user


def actor_for(user_id: uuid.UUID, *, is_admin: bool = False) -> AuthenticatedUser:
    return AuthenticatedUser(
        id=user_id,
        name="Test User",
        email="a@example.com",
        is_admin=is_admin,
        must_change_password=False,
    )


def _no_store_expected(collection: str) -> VectorStore:
    """The factory for tests that must never reach Qdrant.

    Raising rather than returning a fake: a test that unexpectedly triggers a vector
    delete should say so loudly instead of quietly passing against a stub.
    """
    raise AssertionError(f"this test expected no vector store, but one was built for {collection}")


def service_for(
    session: AsyncSession,
    queue: InMemoryIngestionQueue,
    *,
    store_factory: VectorStoreFactory = _no_store_expected,
) -> ProjectService:
    return ProjectService(session, get_settings(), queue, store_factory=store_factory)


async def test_create_enqueues_exactly_one_job(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    response = await service_for(db_session, queue).create(
        ProjectCreateRequest(repo_url="https://github.com/acme/repo.git", branch="main"),
        actor=actor_for(user.id),
    )

    assert response.status == ProjectStatus.PENDING
    assert len(queue.messages) == 1
    assert queue.messages[0].project_id == response.id


async def test_create_rejects_a_url_that_fails_validation(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    with pytest.raises(AppError) as caught:
        await service_for(db_session, queue).create(
            ProjectCreateRequest(repo_url="http://github.com/acme/repo.git"),
            actor=actor_for(user.id),
        )

    assert caught.value.status_code == 400
    assert caught.value.code == ErrorCode.INVALID_REPO_URL
    # Validation runs before the insert, so a rejected URL leaves nothing behind.
    assert queue.messages == []


async def test_the_pat_is_never_returned(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()

    response = await service_for(db_session, InMemoryIngestionQueue()).create(
        ProjectCreateRequest(repo_url="https://github.com/acme/repo.git", pat="ghp_secret"),
        actor=actor_for(user.id),
    )

    assert "ghp_secret" not in response.model_dump_json()


async def test_a_stranger_cannot_delete_someone_elses_project(db_session: AsyncSession) -> None:
    """docs/PRD.md §7: verified by an automated test."""
    owner = await create_user(db_session)
    stranger = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session, InMemoryIngestionQueue()).delete(
            project.id, actor=actor_for(stranger.id)
        )

    # 403, not 404: project existence is deliberately public (docs/PRD.md §4.1).
    assert caught.value.status_code == 403
    assert caught.value.code == ErrorCode.NOT_PROJECT_OWNER


async def test_an_admin_can_delete_any_project(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    admin = await create_user(db_session, is_admin=True)
    project = await create_project(db_session, created_by=owner.id)
    await db_session.commit()

    await service_for(db_session, InMemoryIngestionQueue()).delete(
        project.id, actor=actor_for(admin.id, is_admin=True)
    )
    await db_session.commit()

    assert await ProjectRepository(db_session).get(project.id) is None


async def test_delete_hard_deletes_the_vectors_in_the_recorded_collection(
    db_session: AsyncSession,
) -> None:
    """docs/PRD.md §5.1: vector points have no deleted_at, so they go for real.

    The collection asked for is asserted, not just the emptiness of the store: a
    delete that always built a store for the *wrong* collection would leave the real
    points orphaned forever and still pass a points-are-gone assertion.
    """
    recorded = "code_chunks__ollama__nomic_embed_text__768"
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    project.embedding_collection = recorded
    await db_session.commit()

    store = InMemoryVectorStore(dimensions=4)
    await store.upsert(
        project_id=project.id,
        generation=1,
        chunks=[Chunk("a.py", 1, 2, "python", None, 0, "x = 1")],
        vectors=[[0.1] * 4],
        commit_sha="a" * 40,
    )
    asked: list[str] = []

    def store_for(collection: str) -> VectorStore:
        asked.append(collection)
        return store

    service = service_for(db_session, InMemoryIngestionQueue(), store_factory=store_for)
    await service.delete(project.id, actor=actor_for(owner.id))

    assert asked == [recorded]
    assert store.points == []


async def test_delete_does_not_touch_qdrant_when_nothing_was_ever_indexed(
    db_session: AsyncSession,
) -> None:
    """A project with no `embedding_collection` has no points to delete.

    `_no_store_expected` fails the test if a store is built anyway — which is what
    guessing a collection name from settings would have to do.
    """
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id)
    await db_session.commit()
    assert project.embedding_collection is None

    await service_for(db_session, InMemoryIngestionQueue()).delete(
        project.id, actor=actor_for(owner.id)
    )

    assert await ProjectRepository(db_session).get(project.id) is None


async def test_reindex_enqueues_when_the_project_is_idle(db_session: AsyncSession) -> None:
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id, status=ProjectStatus.READY)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    result = await service_for(db_session, queue).reindex(project.id, actor=actor_for(owner.id))

    assert result.enqueued is True
    assert len(queue.messages) == 1


async def test_reindex_is_a_no_op_while_a_run_is_in_flight(db_session: AsyncSession) -> None:
    """202 either way; the body says which happened (spec §2.2)."""
    owner = await create_user(db_session)
    project = await create_project(db_session, created_by=owner.id, status=ProjectStatus.INDEXING)
    await db_session.commit()
    queue = InMemoryIngestionQueue()

    result = await service_for(db_session, queue).reindex(project.id, actor=actor_for(owner.id))

    assert result.enqueued is False
    assert queue.messages == []


async def test_get_raises_404_for_a_missing_project(db_session: AsyncSession) -> None:
    user = await create_user(db_session)
    await db_session.commit()

    with pytest.raises(AppError) as caught:
        await service_for(db_session, InMemoryIngestionQueue()).get(
            uuid.uuid4(), actor=actor_for(user.id)
        )
    assert caught.value.status_code == 404
