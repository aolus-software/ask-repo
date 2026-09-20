"""Ingestion outcomes reach the project's members.

The guard on `released` is the important part: a lost lease or a project deleted
mid-run must announce nothing, and `released` already answers that question for free
(`app/ingestion/pipeline.py`). This reuses the exact pipeline harness `test_pipeline.py`
already drives to completion, rather than building a second one.
"""

import uuid
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications import NotificationType
from app.db.session import get_sessionmaker
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.cloner import CloneResult
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.errors import TerminalIngestionError
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.notification import NotificationEvent
from app.models.project import ProjectStatus
from app.repositories.project import ProjectRepository
from tests.factories import create_project
from tests.test_pipeline import COMMIT, claim_for, make_repo, pipeline_for


async def _event_types(session: AsyncSession, project_id: uuid.UUID) -> list[str]:
    result = await session.execute(
        select(NotificationEvent.event_type).where(NotificationEvent.project_id == project_id)
    )
    return list(result.scalars().all())


async def test_a_finished_first_index_notifies_members(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    await pipeline_for(db_session, InMemoryVectorStore(dimensions=4), make_repo(tmp_path)).run(
        project_id=project.id, job_id=job_id, worker_id="w0"
    )

    assert await _event_types(db_session, project.id) == [NotificationType.PROJECT_READY.value]


async def test_a_finished_reindex_notifies_members_with_the_reindex_event(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    project = await create_project(db_session, status=ProjectStatus.READY)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    await pipeline_for(db_session, InMemoryVectorStore(dimensions=4), make_repo(tmp_path)).run(
        project_id=project.id, job_id=job_id, worker_id="w0"
    )

    assert await _event_types(db_session, project.id) == [
        NotificationType.PROJECT_REINDEX_FINISHED.value
    ]


async def test_a_terminal_failure_on_a_first_index_notifies_members(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=TerminalIngestionError("Remote branch nope not found in upstream origin"),
    )

    try:
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")
    except TerminalIngestionError:
        pass

    assert await _event_types(db_session, project.id) == [NotificationType.PROJECT_FAILED.value]


async def test_a_terminal_failure_on_a_reindex_notifies_members_with_the_reindex_event(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    project = await create_project(db_session, status=ProjectStatus.READY)
    await db_session.commit()
    job_id = await claim_for(db_session, project.id)

    pipeline = pipeline_for(
        db_session,
        InMemoryVectorStore(dimensions=4),
        tmp_path / "unused",
        fail_with=TerminalIngestionError("Remote branch nope not found in upstream origin"),
    )

    try:
        await pipeline.run(project_id=project.id, job_id=job_id, worker_id="w0")
    except TerminalIngestionError:
        pass

    assert await _event_types(db_session, project.id) == [
        NotificationType.PROJECT_REINDEX_FAILED.value
    ]


async def test_a_worker_that_lost_its_lease_announces_nothing(
    db_session: AsyncSession, tmp_path: Path
) -> None:
    """`released` guards the fan-out: a stolen lease must not announce an outcome
    that belongs to whichever worker actually wins the project."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    project_id = project.id
    store = InMemoryVectorStore(dimensions=4)
    repo = make_repo(tmp_path)
    job_id = await claim_for(db_session, project_id, lease_seconds=-1)

    async def steal_then_clone(validated: object, **kwargs: object) -> CloneResult:
        async with get_sessionmaker()() as other:
            assert await ProjectRepository(other).claim(
                project_id=project_id,
                job_id=uuid.uuid4(),
                worker_id="w1",
                lease_seconds=300,
            )
            await other.commit()
        return CloneResult(path=repo, commit_sha=COMMIT)

    pipeline = IngestionPipeline(
        db_session,
        pipeline_for(db_session, store, repo).settings,
        embedder=FakeEmbedder(dimensions=4),
        store=store,
        chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
        clone_fn=steal_then_clone,
    )
    await pipeline.run(project_id=project_id, job_id=job_id, worker_id="w0")

    assert await _event_types(db_session, project_id) == []
