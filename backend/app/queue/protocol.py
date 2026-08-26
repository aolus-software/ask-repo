"""The queue boundary.

Services depend on this protocol rather than on Kafka, so route and service tests
run without a broker. `KafkaIngestionQueue` (app/queue/producer.py) and
`InMemoryIngestionQueue` are the two implementations.
"""

from typing import Protocol

from app.queue.topics import IngestionMessage


class IngestionQueue(Protocol):
    """Somewhere to put a job so a worker picks it up."""

    async def enqueue(self, message: IngestionMessage) -> None:
        """Publish a job. Raises on failure — the caller decides what that means."""
        ...


class InMemoryIngestionQueue:
    """Test double. Records what it was handed and never fails."""

    def __init__(self) -> None:
        self.messages: list[IngestionMessage] = []

    async def enqueue(self, message: IngestionMessage) -> None:
        """Record the job."""
        self.messages.append(message)
