"""Test MockDataJobMessage round-tripping and mock_data_next_destination."""

import uuid

from app.queue.topics import MockDataJobMessage, mock_data_next_destination


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
