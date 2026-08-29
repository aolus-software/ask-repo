"""The lease claim, which is what makes at-least-once delivery safe."""

import asyncio
import uuid

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.access import ProjectScope
from app.db.session import get_sessionmaker
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository
from tests.factories import create_project, create_user  # added in this task


async def test_claim_succeeds_on_a_pending_project(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)

    claimed = await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()

    assert claimed is True
    await db_session.refresh(project)
    assert project.status == ProjectStatus.CLONING
    assert project.lease_owner == "worker-0"
    assert project.reindex_in_progress is False


async def test_claiming_a_ready_project_starts_a_reindex(db_session: AsyncSession) -> None:
    """A reindex leaves status at `ready` so the project stays queryable."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    repository = ProjectRepository(db_session)

    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()

    await db_session.refresh(project)
    assert project.status == ProjectStatus.READY
    assert project.reindex_in_progress is True


async def test_a_live_lease_blocks_a_second_claim(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)

    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()

    assert not await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )


async def test_an_expired_lease_can_be_reclaimed(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.CLONING)
    repository = ProjectRepository(db_session)
    # Expire it by claiming with a negative lease.
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="dead", lease_seconds=-1
    )
    await db_session.commit()

    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )


async def test_a_completed_job_id_is_not_reclaimed(db_session: AsyncSession) -> None:
    """A redelivered message must not start an unwanted reindex."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    job_id = uuid.uuid4()

    await repository.claim(
        project_id=project.id, job_id=job_id, worker_id="worker-0", lease_seconds=300
    )
    await repository.release(
        project_id=project.id, job_id=job_id, worker_id="worker-0", status=ProjectStatus.READY
    )
    await db_session.commit()

    # The same message arrives again.
    assert not await repository.claim(
        project_id=project.id, job_id=job_id, worker_id="worker-1", lease_seconds=300
    )


async def test_release_refuses_a_soft_deleted_project(db_session: AsyncSession) -> None:
    """docs/PRD.md §5.1: a run must not write onto a project someone deleted mid-index.

    `embedding_collection` is written only by `release`, so a `DELETE` landing here
    finds it NULL and skips Qdrant. If the worker were then allowed to record its
    outcome, the deleted repository's chunk text would stay on the instance forever
    with nothing referencing it.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    job_id = uuid.uuid4()
    await repository.claim(
        project_id=project.id, job_id=job_id, worker_id="worker-0", lease_seconds=300
    )
    await repository.soft_delete(project)
    await db_session.commit()

    released = await repository.release(
        project_id=project.id,
        job_id=job_id,
        worker_id="worker-0",
        status=ProjectStatus.READY,
        embedding_collection="askrepo_fake_4",
    )
    await db_session.commit()

    assert released is False
    row = await repository.get_including_deleted(project.id)
    assert row is not None
    assert row.embedding_collection is None
    # Still where `claim` left it: the refused release wrote nothing at all.
    assert row.status == ProjectStatus.CLONING


async def test_release_refuses_a_worker_that_lost_its_lease(db_session: AsyncSession) -> None:
    """Two workers, one project: only the one that still holds it may record an outcome.

    Otherwise the surviving row can name a generation the winning run has already
    deleted — a `ready` project whose every query returns nothing.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    stale_job = uuid.uuid4()
    await repository.claim(
        project_id=project.id, job_id=stale_job, worker_id="worker-0", lease_seconds=-1
    )
    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )
    await db_session.commit()

    released = await repository.release(
        project_id=project.id,
        job_id=stale_job,
        worker_id="worker-0",
        status=ProjectStatus.READY,
        active_generation=1,
    )
    await db_session.commit()

    assert released is False
    await db_session.refresh(project)
    assert project.lease_owner == "worker-1"
    assert project.active_generation == 0


async def test_abandon_clears_the_reindex_flag(db_session: AsyncSession) -> None:
    """The only way out of `reindex_in_progress` for a run that ends unclassified."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=300
    )
    await db_session.commit()
    await db_session.refresh(project)
    assert project.reindex_in_progress is True

    assert await repository.abandon(project_id=project.id, worker_id="worker-0")
    await db_session.commit()

    await db_session.refresh(project)
    assert project.reindex_in_progress is False
    # The outcome is still the consumer's to decide, so the status is untouched.
    assert project.status == ProjectStatus.READY
    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )


async def test_abandon_refuses_a_worker_that_lost_its_lease(db_session: AsyncSession) -> None:
    """A late loser must not clear the flag the new owner's run is relying on."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-0", lease_seconds=-1
    )
    assert await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="worker-1", lease_seconds=300
    )
    await db_session.commit()

    assert not await repository.abandon(project_id=project.id, worker_id="worker-0")
    await db_session.commit()

    await db_session.refresh(project)
    assert project.lease_owner == "worker-1"
    assert project.reindex_in_progress is True


async def test_exactly_one_of_two_concurrent_claims_wins() -> None:
    """The race the whole design rests on. Two sessions, one row, one winner."""
    sessionmaker = get_sessionmaker()
    async with sessionmaker() as setup:
        project = await create_project(setup, status=ProjectStatus.PENDING)
        await setup.commit()
        project_id = project.id

    async def attempt(worker_id: str) -> bool:
        async with sessionmaker() as session:
            won = await ProjectRepository(session).claim(
                project_id=project_id,
                job_id=uuid.uuid4(),
                worker_id=worker_id,
                lease_seconds=300,
            )
            await session.commit()
            return won

    results = await asyncio.gather(attempt("worker-0"), attempt("worker-1"))
    assert sum(results) == 1


async def test_list_page_applies_a_restricted_scope(db_session: AsyncSession) -> None:
    """Phase 2's enforcement point, exercised now so it cannot silently rot."""
    user = await create_user(db_session)
    visible = await create_project(db_session, created_by=user.id)
    await create_project(db_session, created_by=user.id)
    await db_session.commit()

    rows, total = await ProjectRepository(db_session).list_page(
        scope=ProjectScope.of([visible.id]),
        page=1,
        limit=25,
        search=None,
        sort="created_at",
        descending=True,
    )
    assert total == 1
    assert [row.id for row in rows] == [visible.id]


async def test_list_page_with_an_empty_scope_returns_nothing(db_session: AsyncSession) -> None:
    """An empty id set means *no* access, never all of it."""
    await create_project(db_session)
    await db_session.commit()

    rows, total = await ProjectRepository(db_session).list_page(
        scope=ProjectScope.of([]), page=1, limit=25, search=None, sort="created_at", descending=True
    )
    assert total == 0
    assert list(rows) == []


async def test_unknown_sort_field_raises(db_session: AsyncSession) -> None:
    with pytest.raises(ValueError, match="unknown sort field"):
        await ProjectRepository(db_session).list_page(
            scope=ProjectScope.all(),
            page=1,
            limit=25,
            search=None,
            sort="encrypted_pat",
            descending=True,
        )
