"""One generation message, end to end, with no broker.

Mirrors `test_checklist_consumer.py`'s shape, substituting the dataset lease for the
module lease. Uses `create_checklist_module` + `MockDataDatasetRepository` directly,
matching `test_mock_data_dataset_repository.py`'s pattern -- there is no `make_module`
fixture in this suite.
"""

import uuid
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.models.mock_data import MockDataDatasetStatus
from app.queue.consumer import JobOutcome
from app.queue.mock_data import handle_mock_data_message
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import MockDataJobMessage
from app.rag.errors import RetryableChatError, TerminalChatError
from app.repositories.mock_data_dataset import MockDataDatasetRepository
from tests.factories import create_checklist_module


class _StubGenerator:
    def __init__(self, *, raises: Exception | None = None) -> None:
        self.raises = raises
        self.calls: list[tuple[uuid.UUID, uuid.UUID, str, int]] = []

    async def run(
        self, *, dataset_id: uuid.UUID, job_id: uuid.UUID, worker_id: str, count: int
    ) -> None:
        self.calls.append((dataset_id, job_id, worker_id, count))
        if self.raises is not None:
            raise self.raises


async def test_handle_message_skips_a_refused_claim(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()
    await repo.claim(
        dataset_id=dataset.id, job_id=uuid.uuid4(), worker_id="other", lease_seconds=300
    )
    await db_session.commit()

    generator = _StubGenerator()
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=generator,
        repository=repo,
        producer=InMemoryIngestionQueue(),
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.SKIPPED
    assert generator.calls == []


async def test_handle_message_dead_letters_a_terminal_failure(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    generator = _StubGenerator(raises=TerminalIngestionError("no schema"))
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=generator,
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert producer.produced[0][0] == "askrepo.mock-data.dlq"


async def test_handle_message_retries_a_retryable_failure(db_session: AsyncSession) -> None:
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    generator = _StubGenerator(raises=RetryableIngestionError("scroll blip"))
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=generator,
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    assert producer.produced[0][0] == "askrepo.mock-data.retry.1m"


async def test_handle_message_records_failed_when_the_retry_ladder_is_spent(
    db_session: AsyncSession,
) -> None:
    """The mock-data twin of the checklist regression.

    A retryable failure on the last attempt goes to the dead-letter topic, so deferring
    would leave the dataset `generating` with no lease -- the shape the reconcile sweep
    reads as abandoned, which it would then re-publish forever.
    """
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            # attempt 2 of max_attempts=3: the ladder is spent.
            attempt=2,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=_StubGenerator(raises=RetryableChatError("provider timed out")),
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert producer.produced[0][0] == "askrepo.mock-data.dlq"
    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.FAILED.value
    assert dataset.error is not None
    assert "RetryableChatError" in dataset.error
    assert "provider timed out" not in dataset.error


async def test_handle_message_defers_an_unclassified_failure_on_first_attempt(
    db_session: AsyncSession,
) -> None:
    """Same reasoning as the checklist consumer's
    `test_an_unclassified_first_failure_releases_the_lease_too`: attempt 0 is coming
    back, so it defers rather than failing, and a deferred run holds its lease only
    until the retry is due."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=_StubGenerator(raises=RuntimeError("ollama fell over")),
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    assert producer.produced[0][0] == "askrepo.mock-data.retry.1m"
    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.GENERATING.value
    # Held to the rung's delay, not dropped: a lease-less `generating` row is what the
    # reconcile sweep would publish a second job for.
    assert dataset.lease_expires_at is not None
    assert (dataset.lease_expires_at - datetime.now(UTC)).total_seconds() <= 60


async def test_handle_message_dead_letters_an_unclassified_failure_after_first_retry(
    db_session: AsyncSession,
) -> None:
    """An unclassified error is retried exactly once, so a message already on its
    second attempt (`attempt >= 1`) dead-letters instead of deferring again -- the same
    ladder-length rule `handle_checklist_message` applies."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=1,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=_StubGenerator(raises=RuntimeError("ollama fell over")),
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert producer.produced[0][0] == "askrepo.mock-data.dlq"
    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.FAILED.value


async def test_handle_message_dead_letters_a_terminal_chat_failure(
    db_session: AsyncSession,
) -> None:
    """`TerminalChatError` must be routed exactly like `TerminalIngestionError` -- the
    taxonomy is separate (M4.5 spec 2.1) but the dispatch is shared."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=_StubGenerator(raises=TerminalChatError("unknown model")),
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.DEAD_LETTERED
    assert producer.produced[0][0] == "askrepo.mock-data.dlq"
    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.FAILED.value
    assert dataset.error == "generation failed: TerminalChatError."


async def test_handle_message_retries_a_retryable_chat_failure(
    db_session: AsyncSession,
) -> None:
    """`RetryableChatError` must be routed exactly like `RetryableIngestionError`."""
    module = await create_checklist_module(db_session)
    repo = MockDataDatasetRepository(db_session)
    dataset = await repo.get_or_create_for_module(module.id)
    await db_session.commit()

    producer = InMemoryIngestionQueue()
    outcome = await handle_mock_data_message(
        MockDataJobMessage(
            dataset_id=dataset.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic="askrepo.mock-data.generate",
            count=10,
        ),
        generator=_StubGenerator(raises=RetryableChatError("rate limited")),
        repository=repo,
        producer=producer,
        worker_id="me",
        max_attempts=3,
        session=db_session,
    )

    assert outcome is JobOutcome.RETRY_SCHEDULED
    assert producer.produced[0][0] == "askrepo.mock-data.retry.1m"
    await db_session.refresh(dataset)
    assert dataset.status == MockDataDatasetStatus.GENERATING.value
