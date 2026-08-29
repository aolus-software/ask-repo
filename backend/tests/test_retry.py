"""Waiting out a delay in a log that has no delay primitive."""

import uuid

from app.queue.retry import seconds_until_due
from app.queue.topics import INGEST_TOPIC, IngestionMessage


def message(not_before_ms: int) -> IngestionMessage:
    return IngestionMessage(
        project_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=1,
        not_before_ms=not_before_ms,
        original_topic=INGEST_TOPIC,
    )


def test_a_future_message_reports_the_remaining_wait() -> None:
    assert seconds_until_due(message(60_000), now_ms=0) == 60.0


def test_a_due_message_reports_zero() -> None:
    assert seconds_until_due(message(1_000), now_ms=5_000) == 0.0


def test_an_exactly_due_message_reports_zero() -> None:
    assert seconds_until_due(message(5_000), now_ms=5_000) == 0.0
