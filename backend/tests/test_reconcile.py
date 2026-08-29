"""Recovering jobs that Kafka never got, or that a dead worker was holding."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ProjectStatus
from app.queue.topics import INGEST_TOPIC, IngestionMessage
from app.repositories.project import ProjectRepository
from app.worker import reconcile_once
from tests.factories import create_project


class RecordingProducer:
    def __init__(self) -> None:
        self.sent: list[tuple[str, IngestionMessage]] = []

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        self.sent.append((topic, message))


async def test_a_stranded_pending_project_is_re_enqueued(db_session: AsyncSession) -> None:
    """POST /projects wrote the row but the produce failed. Nothing else recovers it."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    producer = RecordingProducer()

    count = await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    )

    assert count == 1
    assert producer.sent[0][1].project_id == project.id


async def test_a_freshly_created_project_is_left_alone(db_session: AsyncSession) -> None:
    """Its message is probably in flight; two minutes is the grace period."""
    await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    ) == 0
    assert producer.sent == []


async def test_a_project_held_by_a_dead_worker_is_re_enqueued(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="dead", lease_seconds=-1
    )
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(
        repository=repository, producer=producer, topic=INGEST_TOPIC
    ) == 1


async def test_a_healthy_running_job_is_left_alone(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="alive", lease_seconds=300
    )
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(
        repository=repository, producer=producer, topic=INGEST_TOPIC
    ) == 0


async def test_re_enqueued_jobs_get_a_fresh_job_id(db_session: AsyncSession) -> None:
    """The old job_id may already be recorded on the row, which would make the
    replacement message unclaimable."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    producer = RecordingProducer()

    await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    )

    assert producer.sent[0][1].job_id != project.last_job_id
    assert producer.sent[0][1].attempt == 0
