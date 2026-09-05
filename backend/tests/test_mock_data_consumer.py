"""One generation message, end to end, with no broker.

Mirrors `test_checklist_consumer.py`'s shape, substituting the dataset lease for the
module lease. Uses `create_checklist_module` + `MockDataDatasetRepository` directly,
matching `test_mock_data_dataset_repository.py`'s pattern -- there is no `make_module`
fixture in this suite.
"""

import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.ingestion.errors import RetryableIngestionError, TerminalIngestionError
from app.queue.consumer import JobOutcome
from app.queue.mock_data import handle_mock_data_message
from app.queue.protocol import InMemoryIngestionQueue
from app.queue.topics import MockDataJobMessage
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
