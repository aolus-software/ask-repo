"""The queue boundary.

Services depend on these protocols rather than on Kafka, so route and service tests
run without a broker. `KafkaIngestionQueue` (app/queue/producer.py) and
`InMemoryIngestionQueue` are the two implementations, and both satisfy each protocol.

There are two because the two callers need different things. A route only ever asks
for a job to be run, which is `IngestionQueue`. The retry ladder picks the topic
itself — that is the whole mechanism, since the delay lives in the topic a message is
sent to — which is `TopicProducer`.
"""

from typing import Protocol

from app.queue.topics import INGEST_TOPIC, IngestionMessage


class IngestionQueue(Protocol):
    """Somewhere to put a job so a worker picks it up."""

    async def enqueue(self, message: IngestionMessage) -> None:
        """Publish a job. Raises on failure — the caller decides what that means."""
        ...


class TopicProducer(Protocol):
    """Somewhere to put a message on a topic the caller names.

    The consumer's half of the boundary: a failed job is routed onward by choosing
    between the delay topics and the dead-letter topic (`next_destination`), so the
    topic is a parameter rather than a property of the queue.
    """

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        """Publish to a specific topic. Raises on failure."""
        ...


class InMemoryIngestionQueue:
    """Test double. Records what it was handed and never fails.

    Satisfies both protocols, so a consumer test never has to fall back to the
    concrete Kafka class to get `produce_to`.
    """

    def __init__(self) -> None:
        self.messages: list[IngestionMessage] = []
        self.produced: list[tuple[str, IngestionMessage]] = []

    async def enqueue(self, message: IngestionMessage) -> None:
        """Record the job, on the main ingest topic."""
        await self.produce_to(INGEST_TOPIC, message)

    async def produce_to(self, topic: str, message: IngestionMessage) -> None:
        """Record the job and the topic it was routed to."""
        self.produced.append((topic, message))
        self.messages.append(message)
