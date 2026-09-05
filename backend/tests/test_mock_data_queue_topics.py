"""Test MockDataJobMessage round-tripping and mock_data_next_destination."""

import uuid

from app.queue.topics import (
    MOCK_DATA_DLQ_TOPIC,
    MOCK_DATA_TOPIC,
    MOCK_DATA_RETRY_TOPICS,
    JobMessage,
    MockDataJobMessage,
    mock_data_next_destination,
)


def test_mock_data_job_message_round_trips() -> None:
    message = MockDataJobMessage(
        dataset_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=0,
        not_before_ms=1234,
        original_topic="askrepo.mock-data.generate",
        count=10,
    )
    restored = MockDataJobMessage.from_bytes(message.to_bytes())
    assert restored == message
    assert restored.key() == str(message.dataset_id).encode()


def test_mock_data_next_destination_dead_letters_after_attempts_spent() -> None:
    topic, delay = mock_data_next_destination(attempt=5, max_attempts=3)
    assert topic == "askrepo.mock-data.dlq"
    assert delay == 0


def test_mock_data_ladder_ends_at_its_own_dlq() -> None:
    """A separate ladder from ingestion and checklist, so a stuck generation cannot fill
    the queue another job type is waiting in."""
    assert mock_data_next_destination(attempt=0, max_attempts=3)[0].startswith(
        "askrepo.mock-data.retry"
    )
    assert mock_data_next_destination(attempt=2, max_attempts=3) == (MOCK_DATA_DLQ_TOPIC, 0)


def test_mock_data_message_satisfies_the_job_protocol() -> None:
    """MockDataJobMessage is a JobMessage so the retry ladder implementation serves it."""
    message = MockDataJobMessage(
        dataset_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=0,
        not_before_ms=0,
        original_topic=MOCK_DATA_TOPIC,
        count=10,
    )
    assert isinstance(message, JobMessage)
