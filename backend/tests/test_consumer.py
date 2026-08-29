"""Message handling: claim, run, and route the failure.

`handle_message` is separated from the polling loop precisely so it can be tested
without a broker — the loop itself is covered by the integration test in Task 20.

The producer here is `InMemoryIngestionQueue` rather than a local stub: it implements
`TopicProducer`, so using it proves the shared test double is actually fit for the
retry path instead of leaving that to be discovered by the integration test.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.project import ProjectStatus
from app.queue.consumer import JobOutcome, Pipeline, handle_message
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import DLQ_TOPIC, INGEST_TOPIC, RETRY_TOPICS, IngestionMessage
from app.repositories.project import ProjectRepository
from tests.factories import create_project


class StubPipeline:
    """Runs, or raises whatever it was handed."""

    def __init__(self, raises: Exception | None = None) -> None:
        self.raises = raises
        self.runs = 0

    async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        self.runs += 1
        if self.raises is not None:
            raise self.raises


def message_for(project_id: uuid.UUID, *, attempt: int = 0) -> IngestionMessage:
    return IngestionMessage(
        project_id=project_id,
        job_id=uuid.uuid4(),
        attempt=attempt,
        not_before_ms=0,
        original_topic=INGEST_TOPIC,
    )


async def handle(
    session: AsyncSession,
    message: IngestionMessage,
    *,
    pipeline: Pipeline,
    producer: InMemoryIngestionQueue,
    worker_id: str = "w0",
) -> JobOutcome:
    """One `handle_message` call with this suite's standard wiring."""
    return await handle_message(
        message,
        pipeline=pipeline,
        repository=ProjectRepository(session),
        producer=producer,
        worker_id=worker_id,
        max_attempts=3,
        session=session,
    )


async def test_a_claimed_job_runs(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    pipeline = StubPipeline()

    outcome = await handle(
        db_session, message_for(project.id), pipeline=pipeline, producer=InMemoryIngestionQueue()
    )

    assert outcome is JobOutcome.COMPLETED
    assert pipeline.runs == 1


async def test_a_job_held_by_another_worker_is_skipped(db_session: AsyncSession) -> None:
    """At-least-once delivery means duplicates. The lease, not the message, decides."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="other", lease_seconds=300
    )
    await db_session.commit()
    pipeline = StubPipeline()

    outcome = await handle(
        db_session, message_for(project.id), pipeline=pipeline, producer=InMemoryIngestionQueue()
    )

    assert outcome is JobOutcome.SKIPPED
    assert pipeline.runs == 0


async def test_a_retryable_failure_goes_to_the_one_minute_topic(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = InMemoryIngestionQueue()
    original = message_for(project.id, attempt=0)

    outcome = await handle(
        db_session,
        original,
        pipeline=StubPipeline(RetryableIngestionError("network")),
        producer=producer,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    topic, routed = producer.produced[0]
    assert topic == RETRY_TOPICS[0][0]
    assert routed.attempt == 1
    assert routed.not_before_ms > 0
    assert routed.job_id != original.job_id


async def test_a_retry_can_actually_be_claimed(db_session: AsyncSession) -> None:
    """The forwarded attempt needs a job id `claim` has not already recorded.

    `claim` gates on `last_job_id IS DISTINCT FROM :job_id` and sets `last_job_id`
    when it wins, so a retry carrying the original id is skipped the moment it
    arrives. The attempt counter then never advances, the dead-letter release that
    would set `failed` is never reached, and the reconcile sweep re-produces the job
    every 60 seconds — for a post-clone failure, re-cloning and re-embedding the whole
    repository each time.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = InMemoryIngestionQueue()

    first = await handle(
        db_session,
        message_for(project.id),
        pipeline=StubPipeline(RetryableIngestionError("network")),
        producer=producer,
    )
    assert first is JobOutcome.RETRY_SCHEDULED

    # What the real pipeline's retryable handler does on the way out: expire the
    # lease, and leave everything else for the retry to decide.
    await ProjectRepository(db_session).renew_lease(
        project_id=project.id, worker_id="w0", lease_seconds=-1
    )
    await db_session.commit()

    _, forwarded = producer.produced[0]
    pipeline = StubPipeline()
    second = await handle(db_session, forwarded, pipeline=pipeline, producer=producer)

    assert second is JobOutcome.COMPLETED
    assert pipeline.runs == 1


async def test_a_terminal_failure_never_retries(db_session: AsyncSession) -> None:
    """Three attempts on a rejected URL is waste, and parks the project misleadingly."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = InMemoryIngestionQueue()

    outcome = await handle(
        db_session,
        message_for(project.id),
        pipeline=StubPipeline(TerminalIngestionError("branch not found")),
        producer=producer,
    )

    assert outcome is JobOutcome.COMPLETED
    assert producer.produced == []


async def test_exhausted_attempts_go_to_the_dlq(db_session: AsyncSession) -> None:
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = InMemoryIngestionQueue()

    outcome = await handle(
        db_session,
        message_for(project.id, attempt=2),
        pipeline=StubPipeline(RetryableIngestionError("still failing")),
        producer=producer,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert producer.produced[0][0] == DLQ_TOPIC

    await db_session.refresh(project)
    assert project.status == ProjectStatus.FAILED


async def test_dead_lettering_a_reindex_lowers_the_in_progress_flag(
    db_session: AsyncSession,
) -> None:
    """The only path that clears it on a failing run, so it has to be taken.

    The pipeline deliberately leaves `reindex_in_progress` raised on a retryable
    failure, because the job is coming back and a duplicate manual reindex in that
    window would be wrong. Once the attempts are spent nothing is coming back, so if
    this release did not fire the project would answer `enqueued: false` to every
    reindex from then on, stuck on its old index.
    """
    project = await create_project(db_session, status=ProjectStatus.READY)
    await db_session.commit()

    outcome = await handle(
        db_session,
        message_for(project.id, attempt=2),
        pipeline=StubPipeline(RetryableIngestionError("still failing")),
        producer=InMemoryIngestionQueue(),
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    await db_session.refresh(project)
    assert project.reindex_in_progress is False
    assert project.status == ProjectStatus.FAILED
    assert project.lease_owner is None


async def test_an_unexpected_error_retries_once_then_stops(db_session: AsyncSession) -> None:
    """Spec §4.4: a bug should not silently eat jobs, nor loop forever.

    The classified ladder keeps its full budget — a network blip deserves three tries.
    An exception nobody classified does not, so it gets exactly one retry and then
    lands in the dead-letter queue where it is visible.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()
    producer = InMemoryIngestionQueue()

    first = await handle(
        db_session,
        message_for(project.id, attempt=0),
        pipeline=StubPipeline(ValueError("unexpected")),
        producer=producer,
    )
    assert first is JobOutcome.RETRY_SCHEDULED

    # What the real pipeline does on its way out of an unclassified failure: expire
    # the lease and lower the reindex flag, without deciding the outcome. The lease
    # is expired rather than disowned, which is what lets the release below match.
    await ProjectRepository(db_session).abandon(project_id=project.id, worker_id="w0")
    await db_session.commit()

    second = await handle(
        db_session,
        message_for(project.id, attempt=1),
        pipeline=StubPipeline(ValueError("unexpected")),
        producer=producer,
    )
    assert second is JobOutcome.DEAD_LETTERED
    assert producer.produced[1][0] == DLQ_TOPIC

    await db_session.refresh(project)
    assert project.status == ProjectStatus.FAILED


async def test_an_unexpected_errors_text_never_reaches_the_project(
    db_session: AsyncSession,
) -> None:
    """docs/PRD.md §9: a token must not survive into anything an operator can read.

    Unlike the pipeline, this layer holds no PAT and so cannot scrub one out of an
    arbitrary exception's message. It records the exception's class instead, and the
    text goes only to the log.
    """
    pat = "ghp_averysecrettoken"
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    outcome = await handle(
        db_session,
        message_for(project.id, attempt=2),
        pipeline=StubPipeline(RuntimeError(f"failed on https://{pat}@github.com/a/b")),
        producer=InMemoryIngestionQueue(),
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    await db_session.refresh(project)
    assert project.error is not None
    assert pat not in project.error
    assert "RuntimeError" in project.error
