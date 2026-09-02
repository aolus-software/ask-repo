"""Recovering jobs that Kafka never got, or that a dead worker was holding.

The sweep is the only thing standing between "the row committed but the produce
failed" and a project that sits at `pending` forever. It is also the only thing that
frees a lease held by a worker that died mid-index, so both directions matter: too
eager and it duplicates live work, too lazy and jobs are silently lost.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.project import ProjectStatus
from app.queue.topics import INGEST_TOPIC, IngestionMessage, JobMessage
from app.repositories.project import LEASE_SECONDS, ProjectRepository
from app.worker import RECONCILE_INTERVAL_SECONDS, reconcile_once
from tests.factories import create_project


class RecordingProducer:
    """A `TopicProducer` double. Reconcile only ever forwards `IngestionMessage`,
    so `.sent` stays narrow even though `produce_to` accepts any `JobMessage`."""

    def __init__(self) -> None:
        self.sent: list[tuple[str, IngestionMessage]] = []

    async def produce_to(self, topic: str, message: JobMessage) -> None:
        assert isinstance(message, IngestionMessage)  # reconcile only forwards these
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

    assert (
        await reconcile_once(
            repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
        )
        == 0
    )
    assert producer.sent == []


async def test_a_project_held_by_a_dead_worker_is_re_enqueued(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="dead", lease_seconds=-1
    )
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(repository=repository, producer=producer, topic=INGEST_TOPIC) == 1


async def test_a_healthy_running_job_is_left_alone(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    repository = ProjectRepository(db_session)
    await repository.claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="alive", lease_seconds=300
    )
    await db_session.commit()
    producer = RecordingProducer()

    assert await reconcile_once(repository=repository, producer=producer, topic=INGEST_TOPIC) == 0


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


async def test_the_message_goes_to_the_topic_it_was_given(db_session: AsyncSession) -> None:
    """The sweep re-enqueues onto the main ingest topic, never onto a retry rung —
    a recovered job is a fresh attempt, not a delayed one."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    producer = RecordingProducer()

    await reconcile_once(
        repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
    )

    topic, message = producer.sent[0]
    assert topic == INGEST_TOPIC
    assert message.original_topic == INGEST_TOPIC
    assert message.not_before_ms == 0, "a recovered job waits for nothing"


async def test_a_soft_deleted_project_is_not_resurrected(db_session: AsyncSession) -> None:
    """Deleting a project drops its vectors. Re-enqueueing it would rebuild an index
    for something the user removed, and `delete` is the one operation that cannot be
    undone from the UI."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    project.deleted_at = datetime.now(UTC)
    await db_session.commit()
    producer = RecordingProducer()

    assert (
        await reconcile_once(
            repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
        )
        == 0
    )
    assert producer.sent == []


async def test_a_ready_project_is_never_re_enqueued(db_session: AsyncSession) -> None:
    """A finished index has no live lease and no pending status; sweeping it in would
    re-clone and re-embed a repository for no reason, on a shared box."""
    project = await create_project(db_session, status=ProjectStatus.READY)
    project.created_at = datetime.now(UTC) - timedelta(days=1)
    await db_session.commit()
    producer = RecordingProducer()

    assert (
        await reconcile_once(
            repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
        )
        == 0
    )


async def test_every_stranded_project_is_swept_in_one_pass(db_session: AsyncSession) -> None:
    """A restart can strand a batch. Recovering one per minute would take an hour."""
    for _ in range(3):
        project = await create_project(db_session, status=ProjectStatus.PENDING)
        project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    producer = RecordingProducer()

    assert (
        await reconcile_once(
            repository=ProjectRepository(db_session), producer=producer, topic=INGEST_TOPIC
        )
        == 3
    )
    assert len({message.job_id for _, message in producer.sent}) == 3


async def test_a_second_sweep_re_enqueues_again(db_session: AsyncSession) -> None:
    """`reconcile_once` does not mark anything as swept, so two workers ticking at
    once both publish. That is deliberate and safe — `claim` is the deduplication
    boundary — but it means the duplicate must stay cheap, not be prevented here."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    project.created_at = datetime.now(UTC) - timedelta(minutes=5)
    await db_session.commit()
    repository = ProjectRepository(db_session)
    producer = RecordingProducer()

    await reconcile_once(repository=repository, producer=producer, topic=INGEST_TOPIC)
    await reconcile_once(repository=repository, producer=producer, topic=INGEST_TOPIC)

    assert len(producer.sent) == 2
    assert producer.sent[0][1].job_id != producer.sent[1][1].job_id


def test_the_sweep_runs_often_enough_to_meet_the_recovery_promise() -> None:
    """`docs/PRD.md` §7: a killed worker leaves the project reclaimable within five
    minutes. The lease is 300s and the sweep is what notices it lapsed, so a tick
    slower than the lease would blow that budget."""
    assert RECONCILE_INTERVAL_SECONDS <= LEASE_SECONDS
