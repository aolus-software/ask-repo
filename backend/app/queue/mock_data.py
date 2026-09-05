"""Consuming mock-data generation jobs.

Structurally identical to `app/queue/checklist.py`, and deliberately so: the same
lease-is-the-boundary rule, the same failure classification, the same
pause-and-keep-poll loop. What differs is the row that is claimed (the dataset, not the
module) and the ladder a failure is routed onto.
"""

import logging
import time
import uuid
from collections.abc import Callable
from typing import Protocol

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.crypto import scrub as scrub
from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.mock_data import MockDataDatasetStatus
from app.queue.consumer import JobOutcome as JobOutcome
from app.queue.consumer import PausingConsumer
from app.queue.producer import ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.topics import (
    ALL_MOCK_DATA_TOPICS,
    MockDataJobMessage,
    mock_data_next_destination,
)
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.mock_data_dataset import LEASE_SECONDS, MockDataDatasetRepository

logger = logging.getLogger(__name__)


class GenerationRunner(Protocol):
    """The unit of work a mock-data message triggers."""

    async def run(
        self, *, dataset_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, count: int
    ) -> None:
        """Generate one dataset's proposed change set."""
        ...


GeneratorFactory = Callable[[AsyncSession], GenerationRunner]


async def handle_mock_data_message(
    message: MockDataJobMessage,
    *,
    generator: GenerationRunner,
    repository: MockDataDatasetRepository,
    producer: TopicProducer,
    worker_id: str,
    max_attempts: int,
    session: AsyncSession,
) -> JobOutcome:
    """Run one generation. Every returned value means "commit the offset"."""
    if not await repository.claim(
        dataset_id=message.dataset_id,
        job_id=message.job_id,
        worker_id=worker_id,
        lease_seconds=LEASE_SECONDS,
    ):
        await session.commit()
        logger.info("mock data dataset %s is already claimed; skipping", message.dataset_id)
        return JobOutcome.SKIPPED
    await session.commit()

    try:
        await generator.run(
            dataset_id=message.dataset_id,
            job_id=message.job_id,
            worker_id=worker_id,
            count=message.count,
        )
    except (TerminalIngestionError, TerminalChatError) as error:
        logger.warning(
            "mock-data generation for dataset %s failed terminally: %s",
            message.dataset_id,
            error,
        )
        await _fail(
            message,
            repository=repository,
            worker_id=worker_id,
            reason=scrub(f"generation failed: {type(error).__name__}."),
            session=session,
        )
        await _route_failure(message, producer=producer, max_attempts=0)
        return JobOutcome.DEAD_LETTERED
    except (RetryableIngestionError, RetryableChatError) as error:
        await _defer(message, repository=repository, worker_id=worker_id, session=session)
        logger.warning(
            "mock-data generation for dataset %s failed retryably: %s",
            message.dataset_id,
            type(error).__name__,
        )
        await _route_failure(message, producer=producer, max_attempts=max_attempts)
        return JobOutcome.RETRY_SCHEDULED
    except Exception as error:
        logger.exception("unclassified failure generating mock data for %s", message.dataset_id)
        if message.attempt >= 1:
            await _fail(
                message,
                repository=repository,
                worker_id=worker_id,
                reason=f"generation failed with an unexpected {type(error).__name__}.",
                session=session,
            )
            await _route_failure(message, producer=producer, max_attempts=0)
            return JobOutcome.DEAD_LETTERED
        await _defer(message, repository=repository, worker_id=worker_id, session=session)
        await _route_failure(message, producer=producer, max_attempts=max_attempts)
        return JobOutcome.RETRY_SCHEDULED

    return JobOutcome.COMPLETED


async def _defer(
    message: MockDataJobMessage,
    *,
    repository: MockDataDatasetRepository,
    worker_id: str,
    session: AsyncSession,
) -> None:
    """Drop the lease of a run that ended but is coming back."""
    await session.rollback()
    if await repository.defer(dataset_id=message.dataset_id, worker_id=worker_id):
        await session.commit()
    else:
        await session.rollback()


async def _fail(
    message: MockDataJobMessage,
    *,
    repository: MockDataDatasetRepository,
    worker_id: str,
    reason: str,
    session: AsyncSession,
) -> None:
    """Record a terminal failure on the dataset, scrubbed, and drop the lease."""
    if await repository.release(
        dataset_id=message.dataset_id,
        job_id=message.job_id,
        worker_id=worker_id,
        status=MockDataDatasetStatus.FAILED,
        error=reason,
    ):
        await session.commit()
    else:
        await session.rollback()


async def _route_failure(
    message: MockDataJobMessage, *, producer: TopicProducer, max_attempts: int
) -> None:
    """Send the job onward: a delay rung, or the mock-data dead-letter topic."""
    topic, delay_seconds = mock_data_next_destination(
        attempt=message.attempt, max_attempts=max_attempts
    )
    await producer.produce_to(
        topic,
        MockDataJobMessage(
            dataset_id=message.dataset_id,
            job_id=uuid.uuid4(),
            attempt=message.attempt + 1,
            not_before_ms=int(time.time() * 1000) + delay_seconds * 1000,
            original_topic=message.original_topic,
            count=message.count,
        ),
    )


class MockDataConsumer(PausingConsumer[MockDataJobMessage]):
    """The generation polling loop for one worker.

    Inherits the pause-and-keep-polling loop for the same reason
    `ChecklistConsumer` does: a large module's source can take a chat model minutes to
    process, well past `max.poll.interval.ms`.
    """

    def __init__(
        self,
        *,
        settings: Settings,
        sessionmaker: async_sessionmaker[AsyncSession],
        producer: TopicProducer,
        build_generator: GeneratorFactory,
        worker_id: str,
    ) -> None:
        self.settings = settings
        self.sessionmaker = sessionmaker
        self.producer = producer
        self.build_generator = build_generator
        self.worker_id = worker_id
        self.topic = settings.kafka_mock_data_topic
        # Its own group: sharing checklist's or ingestion's would drag all three into
        # one rebalance.
        self.group_id = f"{settings.kafka_consumer_group}-mock-data"
        self._job_in_flight = False

    def _decode(self, raw: bytes) -> MockDataJobMessage:
        return MockDataJobMessage.from_bytes(raw)

    async def _ensure_topics(self) -> None:
        """Idempotent, which is what makes calling it here and in the API correct."""
        await ensure_topics(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            partitions=self.settings.kafka_mock_data_partitions,
            topics=ALL_MOCK_DATA_TOPICS,
        )

    async def _run_job(self, message: MockDataJobMessage) -> JobOutcome:
        """One generation, in its own session."""
        async with self.sessionmaker() as session:
            return await handle_mock_data_message(
                message,
                generator=self.build_generator(session),
                repository=MockDataDatasetRepository(session),
                producer=self.producer,
                worker_id=self.worker_id,
                max_attempts=self.settings.kafka_max_attempts,
                session=session,
            )
