"""Consuming ingestion jobs.

Three things here are the difference between working and quietly corrupting a project.

**Pausing.** Kafka's group protocol treats a consumer that stops calling `poll()` as
dead, and `max.poll.interval.ms` defaults to five minutes — far less than indexing a
real repository takes. So the loop pauses, runs the job as a task, and keeps polling:
a paused partition returns no records, the member stays alive, and no rebalance fires.
Raising `max.poll.interval.ms` instead would mean guessing at the slowest repository
anyone will ever index.

**Claiming.** Even with pausing, delivery is at-least-once, and `IngestionMessage.key`
only orders a project's messages within one topic — the retry ladder crosses topics.
The claim in `ProjectRepository` is the actual deduplication boundary; this module
trusts it and not the message.

**A fresh job id per attempt.** `claim` refuses a job id it has already completed, so
a retry carrying the original id could never be claimed and would be skipped until its
attempts ran out. Each forwarded attempt therefore gets a new id: the dedup is about a
redelivered *message*, not about a deliberate retry.
"""

import asyncio
import logging
import time
import uuid
from collections.abc import Callable
from enum import StrEnum
from typing import Protocol

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.ingestion.pipeline import MAX_RECORDED_ERROR_CHARS
from app.models.project import ProjectStatus
from app.queue.producer import ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.topics import DLQ_TOPIC, IngestionMessage, next_destination
from app.repositories.project import ProjectRepository

logger = logging.getLogger(__name__)

LEASE_SECONDS = 300
POLL_TIMEOUT_MS = 1000


class JobOutcome(StrEnum):
    """What happened to one message. Every value means "commit the offset"."""

    COMPLETED = "completed"
    SKIPPED = "skipped"
    RETRY_SCHEDULED = "retry_scheduled"
    DEAD_LETTERED = "dead_lettered"


class Pipeline(Protocol):
    """The unit of work a message triggers."""

    async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
        """Index one project."""
        ...


PipelineFactory = Callable[[AsyncSession], Pipeline]


async def handle_message(
    message: IngestionMessage,
    *,
    pipeline: Pipeline,
    repository: ProjectRepository,
    producer: TopicProducer,
    worker_id: str,
    max_attempts: int,
    session: AsyncSession,
) -> JobOutcome:
    """Claim, run, and route one job.

    Separated from the polling loop so it is testable without a broker. Every return
    value means the offset should be committed — a message is never left uncommitted
    to be redelivered, because redelivery is exactly what the retry topics are for.
    """
    claimed = await repository.claim(
        project_id=message.project_id,
        job_id=message.job_id,
        worker_id=worker_id,
        lease_seconds=LEASE_SECONDS,
    )
    await session.commit()

    if not claimed:
        # Another worker holds a live lease, or this job already completed.
        logger.info("skipping project %s: not claimable", message.project_id)
        return JobOutcome.SKIPPED

    try:
        await pipeline.run(
            project_id=message.project_id, job_id=message.job_id, worker_id=worker_id
        )
    except TerminalIngestionError:
        # The pipeline already recorded `failed` and the reason on the project.
        logger.warning("project %s failed terminally", message.project_id)
        return JobOutcome.COMPLETED
    except RetryableIngestionError as error:
        # Safe to record: every `IngestionError` the cloner raises is built from
        # already-scrubbed stderr (`app/ingestion/cloner.py`).
        return await _route_failure(
            message,
            producer=producer,
            repository=repository,
            session=session,
            worker_id=worker_id,
            max_attempts=max_attempts,
            reason=str(error),
        )
    except Exception as error:
        logger.exception("project %s raised an unexpected error", message.project_id)
        # The class name only. An arbitrary exception's text may quote a clone URL,
        # and unlike the pipeline this layer has no PAT to scrub it with
        # (`docs/PRD.md` §9). The traceback goes to the operator's log instead.
        return await _route_failure(
            message,
            producer=producer,
            repository=repository,
            session=session,
            worker_id=worker_id,
            max_attempts=max_attempts,
            reason=f"Indexing failed with an unexpected {type(error).__name__}.",
            unexpected=True,
        )

    return JobOutcome.COMPLETED


async def _route_failure(
    message: IngestionMessage,
    *,
    producer: TopicProducer,
    repository: ProjectRepository,
    session: AsyncSession,
    worker_id: str,
    max_attempts: int,
    reason: str,
    unexpected: bool = False,
) -> JobOutcome:
    """Send a failed job to the next retry topic, or to the DLQ if spent.

    `unexpected` shortens the ladder to a single retry, per spec §4.4: an unclassified
    error is retried once and terminal thereafter, so a bug neither silently eats jobs
    nor loops forever. The classified ladder keeps its full budget — a network blip
    genuinely deserves three tries, and an unrecognised exception does not.
    """
    if unexpected and message.attempt >= 1:
        topic, delay_seconds = DLQ_TOPIC, 0
    else:
        topic, delay_seconds = next_destination(attempt=message.attempt, max_attempts=max_attempts)

    forwarded = IngestionMessage(
        project_id=message.project_id,
        # A new id, or `claim` would refuse the retry it just recorded as completed.
        job_id=uuid.uuid4(),
        attempt=message.attempt + 1,
        not_before_ms=int(time.time() * 1000) + delay_seconds * 1000,
        original_topic=message.original_topic,
    )
    await producer.produce_to(topic, forwarded)

    if topic != DLQ_TOPIC:
        return JobOutcome.RETRY_SCHEDULED

    # Nothing else will pick this up, so the project must stop looking busy. This is
    # also the only thing that clears `reindex_in_progress` on a failing run: the
    # pipeline deliberately leaves it raised while a job is still coming back.
    released = await repository.release(
        project_id=message.project_id,
        job_id=message.job_id,
        worker_id=worker_id,
        status=ProjectStatus.FAILED,
        error=reason[:MAX_RECORDED_ERROR_CHARS],
    )
    await session.commit()
    if not released:
        # Deleted mid-run, or reclaimed by another worker. Either way the outcome is
        # not ours to write, and whoever holds it now will write its own.
        logger.warning(
            "dead-lettered project %s but could not record the outcome: no longer ours",
            message.project_id,
        )
    return JobOutcome.DEAD_LETTERED


class IngestionConsumer:
    """The polling loop for one worker."""

    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: TopicProducer,
        build_pipeline: PipelineFactory,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.producer = producer
        self.build_pipeline = build_pipeline
        self.worker_id = worker_id

    async def run(self) -> None:
        """Poll, pause, process, commit, resume — forever."""
        # The worker may start before the API ever has, and broker auto-creation is
        # off, so without this it would idle on topics that do not exist. Idempotent,
        # which is what makes calling it in both processes correct rather than
        # redundant.
        await ensure_topics(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            partitions=self.settings.kafka_ingest_partitions,
        )

        consumer = AIOKafkaConsumer(
            self.settings.kafka_ingest_topic,
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_consumer_group,
            # The offset moves only after the work is done and durable.
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        await consumer.start()
        try:
            while True:
                batches = await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
                for partition, records in batches.items():
                    for record in records:
                        await self._process(consumer, partition, record)
        finally:
            await consumer.stop()

    async def _process(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        record: ConsumerRecord[bytes, bytes],
    ) -> None:
        """Run one record with every assigned partition paused.

        Pausing is what keeps the member alive across a job far longer than
        `max.poll.interval.ms`: the loop keeps calling `getmany`, which returns
        nothing while everything is paused, so the broker never concludes we died.

        *Every* partition, not just this one. The keep-alive `getmany` discards what
        it returns, and `commit()` would then persist the advanced position of a
        partition whose records were thrown away — jobs lost with no redelivery. The
        commit is likewise scoped to the offset actually processed.
        """
        message = IngestionMessage.from_bytes(record.value)
        paused = list(consumer.assignment())
        consumer.pause(*paused)
        try:
            job = asyncio.create_task(self._run_job(message))
            while not job.done():
                # Keep polling so the group protocol stays satisfied. Returns nothing:
                # everything is paused.
                await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS)
            await job
            await consumer.commit({partition: record.offset + 1})
        finally:
            consumer.resume(*paused)

    async def _run_job(self, message: IngestionMessage) -> JobOutcome:
        """One job, in its own session."""
        async with self.sessionmaker() as session:
            return await handle_message(
                message,
                pipeline=self.build_pipeline(session),
                repository=ProjectRepository(session),
                producer=self.producer,
                worker_id=self.worker_id,
                max_attempts=self.settings.kafka_max_attempts,
                session=session,
            )
