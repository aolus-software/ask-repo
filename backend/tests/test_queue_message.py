"""The wire format for an ingestion job."""

import uuid

from app.queue.protocol import InMemoryIngestionQueue, TopicProducer
from app.queue.topics import (
    DLQ_TOPIC,
    INGEST_TOPIC,
    RETRY_TOPICS,
    IngestionMessage,
    next_destination,
)


def message(**overrides: object) -> IngestionMessage:
    defaults = {
        "project_id": uuid.uuid4(),
        "job_id": uuid.uuid4(),
        "attempt": 0,
        "not_before_ms": 0,
        "original_topic": "askrepo.ingest.requested",
    }
    return IngestionMessage(**{**defaults, **overrides})  # type: ignore[arg-type]  # test builder


def test_round_trips_through_bytes() -> None:
    original = message()
    assert IngestionMessage.from_bytes(original.to_bytes()) == original


def test_key_is_the_project_id_so_retries_share_a_partition() -> None:
    project_id = uuid.uuid4()
    assert message(project_id=project_id).key() == str(project_id).encode()


def test_first_failure_goes_to_the_one_minute_topic() -> None:
    topic, delay = next_destination(attempt=0, max_attempts=3)
    assert topic == RETRY_TOPICS[0][0]
    assert delay == 60


def test_second_failure_goes_to_the_ten_minute_topic() -> None:
    topic, delay = next_destination(attempt=1, max_attempts=3)
    assert topic == RETRY_TOPICS[1][0]
    assert delay == 600


def test_exhausted_attempts_go_to_the_dlq() -> None:
    topic, delay = next_destination(attempt=2, max_attempts=3)
    assert topic == DLQ_TOPIC
    assert delay == 0


async def test_the_in_memory_queue_records_what_it_was_given() -> None:
    queue = InMemoryIngestionQueue()
    sent = message()
    await queue.enqueue(sent)
    assert queue.messages == [sent]
    assert queue.produced == [(INGEST_TOPIC, sent)]


async def test_the_in_memory_queue_can_stand_in_for_the_retry_producer() -> None:
    """The retry ladder routes by topic, so the test double has to record the topic.

    Without `produce_to` here, a consumer test would have to take the concrete
    `KafkaIngestionQueue` and give up running without a broker.
    """
    producer: TopicProducer = InMemoryIngestionQueue()
    sent = message(attempt=1)
    await producer.produce_to(DLQ_TOPIC, sent)

    assert isinstance(producer, InMemoryIngestionQueue)
    assert producer.produced == [(DLQ_TOPIC, sent)]
