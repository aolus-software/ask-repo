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

from aiokafka import (
    AIOKafkaConsumer,
    ConsumerRebalanceListener,
    ConsumerRecord,
    TopicPartition,
)
from aiokafka.errors import CommitFailedError, IllegalStateError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.project import MAX_RECORDED_ERROR_CHARS, ProjectStatus
from app.queue.producer import ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.topics import DLQ_TOPIC, IngestionMessage, next_destination
from app.repositories.project import LEASE_SECONDS, ProjectRepository

logger = logging.getLogger(__name__)

POLL_TIMEOUT_MS = 1000
# A brief pause after an unhandled error, so a persistent broker fault backs off
# instead of spinning the loop at full speed.
ERROR_BACKOFF_SECONDS = 1.0


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
    # the normal way `reindex_in_progress` comes down on a failing run — the pipeline
    # deliberately leaves it raised while a job is still coming back — but it is not a
    # guarantee: a crash between the produce above and this write leaves the flag up,
    # and the redelivered message is refused by `claim` because `last_job_id` already
    # names the job. Spec §4.5's reconcile sweep is what recovers that project, once
    # the lease expires. Task 19 owes it.
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


class _RepauseOnRebalance(ConsumerRebalanceListener):
    """Re-applies the pause as part of the rebalance itself.

    A rebalance rebuilds per-partition state **un-paused**, and re-pausing from the
    keep-alive loop is a tick too late: a `getmany` already in flight when the
    rebalance lands fetches from the freshly assigned partitions before the loop
    comes round again, and the loop discards whatever it is handed. Those jobs are
    never redelivered to this process.

    `on_partitions_assigned` runs inside the rebalance, before any fetch, so there is
    no window at all. This is the load-bearing re-pause; the one in the keep-alive
    loop is a cheap backstop for an assignment gained without a callback.
    """

    def __init__(self, consumer: AIOKafkaConsumer, is_busy: Callable[[], bool]) -> None:
        self._consumer = consumer
        self._is_busy = is_busy

    async def on_partitions_revoked(self, revoked: list[TopicPartition]) -> None:
        """Nothing to do: the lease, not the offset, decides who runs a job."""

    async def on_partitions_assigned(self, assigned: list[TopicPartition]) -> None:
        """Pause anything handed to us while a job is still running."""
        if assigned and self._is_busy():
            self._consumer.pause(*assigned)


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
        # Read by the rebalance listener: partitions handed to us mid-job must
        # arrive paused, or the keep-alive poll starts eating real work.
        self._job_in_flight = False

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
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            group_id=self.settings.kafka_consumer_group,
            # The offset moves only after the work is done and durable.
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        # Subscribed here rather than in the constructor so a rebalance listener can
        # be attached — see `_RepauseOnRebalance`.
        consumer.subscribe(
            topics=[self.settings.kafka_ingest_topic],
            listener=_RepauseOnRebalance(consumer, lambda: self._job_in_flight),
        )
        await consumer.start()
        try:
            while True:
                batches = await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
                for partition, records in batches.items():
                    for record in records:
                        await self._process_guarded(consumer, partition, record)
        finally:
            await consumer.stop()

    async def _process_guarded(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        record: ConsumerRecord[bytes, bytes],
    ) -> None:
        """Run one record, absorbing anything it raises.

        A worker that dies on one record never makes progress: it restarts, reads the
        same uncommitted offset, and dies again. Everything here is survivable because
        the database lease, not the offset, is the deduplication boundary (spec §4.2)
        — the worst a redelivery costs is one refused claim.
        """
        try:
            await self._process(consumer, partition, record)
        except Exception:
            logger.exception("failed to process %s offset %s; continuing", partition, record.offset)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)

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

        *Every* partition, not just this one — the keep-alive poll discards what it
        returns, so an unpaused sibling partition has its jobs read and thrown away,
        and they are never redelivered to this process.

        And re-paused on every tick. A rebalance rebuilds the assignment with fresh
        per-partition state that starts un-paused, so a partition this worker keeps
        across a rebalance silently loses its pause mid-job. `pause` is a no-op on a
        partition already paused, which is what makes re-applying it cheap.
        """
        try:
            message = IngestionMessage.from_bytes(record.value)
        except (TypeError, ValueError, KeyError):
            # Unparseable: no redelivery will fix it, and leaving the offset here makes
            # this record a wall the worker restarts into forever. Move past it.
            logger.exception(
                "discarding unparseable record at %s offset %s", partition, record.offset
            )
            await self._commit(consumer, partition, record)
            return

        paused = self._pause_assigned(consumer)
        self._job_in_flight = True
        try:
            job = asyncio.create_task(self._run_job(message))
            while not job.done():
                self._pause_assigned(consumer)
                # Keep polling so the group protocol stays satisfied. Returns nothing:
                # everything assigned is paused.
                await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS)
            await job
            await self._commit(consumer, partition, record)
        finally:
            self._job_in_flight = False
            self._resume(consumer, paused)

    def _pause_assigned(self, consumer: AIOKafkaConsumer) -> list[TopicPartition]:
        """Pause every currently assigned partition, and report which those were."""
        assigned = list(consumer.assignment())
        if assigned:
            consumer.pause(*assigned)
        return assigned

    def _resume(self, consumer: AIOKafkaConsumer, paused: list[TopicPartition]) -> None:
        """Resume only what we paused *and* still hold.

        A rebalance can take a partition away mid-job, and `resume` raises
        `IllegalStateError` for one that is no longer assigned — which would otherwise
        escape a `finally` and end the polling loop.
        """
        still_ours = [partition for partition in paused if partition in consumer.assignment()]
        if still_ours:
            consumer.resume(*still_ours)

    async def _commit(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        record: ConsumerRecord[bytes, bytes],
    ) -> None:
        """Move this partition's offset past the record, if it is still ours.

        Losing the partition mid-job means the offset is not ours to move. Whoever
        holds it now will be given the record again, and `ProjectRepository.claim`
        refuses the duplicate because `last_job_id` already names the job (spec §4.2)
        — which is exactly why a failed commit is survivable rather than a lost job.
        """
        try:
            await consumer.commit({partition: record.offset + 1})
        except (IllegalStateError, CommitFailedError):
            logger.warning(
                "could not commit %s offset %s: the partition is no longer ours",
                partition,
                record.offset,
            )

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
