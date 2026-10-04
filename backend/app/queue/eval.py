"""Consuming eval jobs.

Structurally identical to `app/queue/mock_data.py`; what differs is that one topic
carries two kinds, and the kind picks which row is leased and which runner runs.

Error text never leaves this module. A generator or runner puts provider and Qdrant
exception messages inside the exceptions it raises, and those can echo a prompt, a
retrieved excerpt or a secret. So what is stored on `eval_sets.error` /
`eval_runs.error` and what reaches a log line is the exception's *class name* only,
never its message and never a traceback.
"""

import logging
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.eval import EvalRunStatus, EvalSetStatus
from app.queue.consumer import JobOutcome as JobOutcome
from app.queue.consumer import PausingConsumer
from app.queue.producer import ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.topics import (
    ALL_EVAL_TOPICS,
    EvalJobMessage,
    eval_next_destination,
    eval_retries_exhausted,
)
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.eval_run import EvalRunRepository
from app.repositories.eval_set import LEASE_SECONDS, EvalSetRepository

logger = logging.getLogger(__name__)


class EvalJobRunner(Protocol):
    """A `generate` or `run` unit of work."""

    async def run(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, attempt: int = 0
    ) -> None:
        """Do the job for this target."""
        ...


class EvalLease(Protocol):
    """The lease surface both eval repositories share, keyed by the target row."""

    async def claim(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take the lease. True if won."""
        ...

    async def defer(self, *, target_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Shorten the lease to the retry delay."""
        ...

    async def fail(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, reason: str
    ) -> bool:
        """Record a terminal failure and drop the lease."""
        ...


@dataclass(frozen=True, slots=True)
class EvalRunners:
    """Builders for one job's session: the runner for each kind."""

    build_generator: Callable[[AsyncSession], EvalJobRunner]
    build_runner: Callable[[AsyncSession], EvalJobRunner]


class _SetLease:
    """`EvalSetRepository` keyed by target id."""

    def __init__(self, repository: EvalSetRepository) -> None:
        self.repository = repository

    async def claim(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take the set's lease."""
        return await self.repository.claim(
            set_id=target_id, job_id=job_id, worker_id=worker_id, lease_seconds=lease_seconds
        )

    async def defer(self, *, target_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Shorten the set's lease."""
        return await self.repository.defer(
            set_id=target_id, worker_id=worker_id, hold_seconds=hold_seconds
        )

    async def fail(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, reason: str
    ) -> bool:
        """Release the set `failed`."""
        return await self.repository.release(
            set_id=target_id,
            job_id=job_id,
            worker_id=worker_id,
            status=EvalSetStatus.FAILED,
            error=reason,
        )


class _RunLease:
    """`EvalRunRepository` keyed by target id."""

    def __init__(self, repository: EvalRunRepository) -> None:
        self.repository = repository

    async def claim(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, lease_seconds: int
    ) -> bool:
        """Take the run's lease."""
        return await self.repository.claim(
            run_id=target_id, job_id=job_id, worker_id=worker_id, lease_seconds=lease_seconds
        )

    async def defer(self, *, target_id: uuid.UUID, worker_id: str, hold_seconds: int) -> bool:
        """Shorten the run's lease."""
        return await self.repository.defer(
            run_id=target_id, worker_id=worker_id, hold_seconds=hold_seconds
        )

    async def fail(
        self, *, target_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, reason: str
    ) -> bool:
        """Release the run `failed`."""
        return await self.repository.release(
            run_id=target_id,
            job_id=job_id,
            worker_id=worker_id,
            status=EvalRunStatus.FAILED,
            error=reason,
        )


async def handle_eval_message(
    message: EvalJobMessage,
    *,
    runners: EvalRunners,
    session: AsyncSession,
    producer: TopicProducer,
    worker_id: str,
    max_attempts: int,
) -> JobOutcome:
    """Run one eval job. Every returned value means "commit the offset"."""
    lease: EvalLease
    runner: EvalJobRunner
    if message.kind == "generate":
        lease = _SetLease(EvalSetRepository(session))
        runner = runners.build_generator(session)
    else:
        lease = _RunLease(EvalRunRepository(session))
        runner = runners.build_runner(session)

    if not await lease.claim(
        target_id=message.target_id,
        job_id=message.job_id,
        worker_id=worker_id,
        lease_seconds=LEASE_SECONDS,
    ):
        await session.commit()
        logger.info(
            "eval %s job for %s is already claimed; skipping", message.kind, message.target_id
        )
        return JobOutcome.SKIPPED
    await session.commit()

    try:
        await runner.run(
            target_id=message.target_id,
            job_id=message.job_id,
            worker_id=worker_id,
            attempt=message.attempt,
        )
    except (TerminalIngestionError, TerminalChatError) as error:
        logger.warning(
            "eval %s job for %s failed terminally: %s",
            message.kind,
            message.target_id,
            type(error).__name__,
        )
        await _fail(
            message,
            lease=lease,
            worker_id=worker_id,
            reason=f"{message.kind} failed: {type(error).__name__}.",
            session=session,
        )
        await _route_failure(message, producer=producer, max_attempts=0)
        return JobOutcome.DEAD_LETTERED
    except (RetryableIngestionError, RetryableChatError) as error:
        if eval_retries_exhausted(attempt=message.attempt, max_attempts=max_attempts):
            # Spent ladder: deferring would leave the row in progress with no lease,
            # and the reconcile sweep would re-publish it forever.
            logger.warning(
                "eval %s job for %s exhausted its retries: %s",
                message.kind,
                message.target_id,
                type(error).__name__,
            )
            await _fail(
                message,
                lease=lease,
                worker_id=worker_id,
                reason=(
                    f"{message.kind} failed after {message.attempt + 1} attempts: "
                    f"{type(error).__name__}."
                ),
                session=session,
            )
            await _route_failure(message, producer=producer, max_attempts=max_attempts)
            return JobOutcome.DEAD_LETTERED
        await _defer(
            message, lease=lease, worker_id=worker_id, session=session, max_attempts=max_attempts
        )
        logger.warning(
            "eval %s job for %s failed retryably: %s",
            message.kind,
            message.target_id,
            type(error).__name__,
        )
        await _route_failure(message, producer=producer, max_attempts=max_attempts)
        return JobOutcome.RETRY_SCHEDULED
    except Exception as error:
        # Class name only, and no traceback: its message may carry content.
        logger.error(
            "unclassified failure in eval %s job for %s: %s",
            message.kind,
            message.target_id,
            type(error).__name__,
        )
        if message.attempt >= 1:
            await _fail(
                message,
                lease=lease,
                worker_id=worker_id,
                reason=f"{message.kind} failed with an unexpected {type(error).__name__}.",
                session=session,
            )
            await _route_failure(message, producer=producer, max_attempts=0)
            return JobOutcome.DEAD_LETTERED
        await _defer(
            message, lease=lease, worker_id=worker_id, session=session, max_attempts=max_attempts
        )
        await _route_failure(message, producer=producer, max_attempts=max_attempts)
        return JobOutcome.RETRY_SCHEDULED

    return JobOutcome.COMPLETED


async def _defer(
    message: EvalJobMessage,
    *,
    lease: EvalLease,
    worker_id: str,
    session: AsyncSession,
    max_attempts: int,
) -> None:
    """Hand back a job that ended but is coming back, until its retry is due."""
    _, delay_seconds = eval_next_destination(attempt=message.attempt, max_attempts=max_attempts)
    await session.rollback()
    if await lease.defer(
        target_id=message.target_id, worker_id=worker_id, hold_seconds=delay_seconds
    ):
        await session.commit()
    else:
        await session.rollback()


async def _fail(
    message: EvalJobMessage,
    *,
    lease: EvalLease,
    worker_id: str,
    reason: str,
    session: AsyncSession,
) -> None:
    """Record a terminal failure on the target and drop the lease."""
    await session.rollback()
    if await lease.fail(
        target_id=message.target_id, job_id=message.job_id, worker_id=worker_id, reason=reason
    ):
        await session.commit()
    else:
        await session.rollback()


async def _route_failure(
    message: EvalJobMessage, *, producer: TopicProducer, max_attempts: int
) -> None:
    """Send the job onward: a delay rung, or the eval dead-letter topic."""
    topic, delay_seconds = eval_next_destination(attempt=message.attempt, max_attempts=max_attempts)
    await producer.produce_to(
        topic,
        EvalJobMessage(
            kind=message.kind,
            target_id=message.target_id,
            job_id=uuid.uuid4(),
            attempt=message.attempt + 1,
            not_before_ms=int(time.time() * 1000) + delay_seconds * 1000,
            original_topic=message.original_topic,
        ),
    )


class EvalConsumer(PausingConsumer[EvalJobMessage]):
    """The eval polling loop for one worker.

    Inherits the pause-and-keep-polling loop: a generation or a run can take a chat
    model many minutes, well past `max.poll.interval.ms`.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: TopicProducer,
        runners: EvalRunners,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.producer = producer
        self.runners = runners
        self.worker_id = worker_id
        self.topic = settings.kafka_eval_topic
        self.group_id = f"{settings.kafka_consumer_group}-eval"
        self._job_in_flight = False

    def _decode(self, raw: bytes) -> EvalJobMessage:
        return EvalJobMessage.from_bytes(raw)

    async def _ensure_topics(self) -> None:
        """Idempotent, which is what makes calling it here and in the API correct."""
        await ensure_topics(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            partitions=self.settings.kafka_eval_partitions,
            topics=ALL_EVAL_TOPICS,
        )

    async def _run_job(self, message: EvalJobMessage) -> JobOutcome:
        """One job, in its own session."""
        async with self.sessionmaker() as session:
            return await handle_eval_message(
                message,
                runners=self.runners,
                session=session,
                producer=self.producer,
                worker_id=self.worker_id,
                max_attempts=self.settings.kafka_max_attempts,
            )
