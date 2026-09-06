"""Publishing ingestion jobs to Kafka."""

import logging

from aiokafka import AIOKafkaProducer
from aiokafka.admin import AIOKafkaAdminClient, NewTopic
from aiokafka.errors import TopicAlreadyExistsError, for_code

from app.queue.topics import (
    ALL_TOPICS,
    INGEST_TOPIC,
    ChecklistJobMessage,
    IngestionMessage,
    JobMessage,
    MockDataJobMessage,
)

logger = logging.getLogger(__name__)

# Kafka protocol error codes, as they arrive in a CreateTopicsResponse.
_NO_ERROR = 0
_TOPIC_ALREADY_EXISTS = TopicAlreadyExistsError.errno


class KafkaIngestionQueue:
    """The real queue. Started and stopped by the application lifespan."""

    def __init__(
        self,
        *,
        bootstrap_servers: str,
        topic: str = INGEST_TOPIC,
        checklist_topic: str,
        mock_data_topic: str,
    ) -> None:
        self.topic = topic
        self.checklist_topic = checklist_topic
        self.mock_data_topic = mock_data_topic
        self._bootstrap_servers = bootstrap_servers
        self._producer: AIOKafkaProducer | None = None

    async def start(self) -> None:
        """Connect to the broker."""
        self._producer = AIOKafkaProducer(
            bootstrap_servers=self._bootstrap_servers,
            # Without idempotence a retried produce appends the message twice, and
            # a duplicate job costs a wasted claim attempt on the worker side.
            enable_idempotence=True,
            acks="all",
        )
        await self._producer.start()

    async def stop(self) -> None:
        """Flush and disconnect."""
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    async def enqueue(self, message: IngestionMessage) -> None:
        """Publish a job to the main ingest topic."""
        await self.produce_to(self.topic, message)

    async def enqueue_checklist(self, message: ChecklistJobMessage) -> None:
        """Publish a generation job to the checklist topic."""
        await self.produce_to(self.checklist_topic, message)

    async def enqueue_mock_data(self, message: MockDataJobMessage) -> None:
        """Publish a generation job to the mock-data topic."""
        await self.produce_to(self.mock_data_topic, message)

    async def produce_to(self, topic: str, message: JobMessage) -> None:
        """Publish to a specific topic — used by the retry and DLQ paths."""
        if self._producer is None:
            raise RuntimeError("KafkaIngestionQueue is not started")
        await self._producer.send_and_wait(topic, value=message.to_bytes(), key=message.key())


async def ensure_topics(
    *, bootstrap_servers: str, partitions: int, topics: tuple[str, ...] = ALL_TOPICS
) -> None:
    """Create the topics if they are absent. Idempotent, so both processes may call it.

    `topics` is a parameter rather than a constant because M4 adds a second family
    (`ALL_CHECKLIST_TOPICS`) with its own partition count -- generation's instance-wide
    cap is one partition, ingestion's is two.

    Explicit rather than relying on broker auto-creation: auto-created topics get
    one partition, which would silently halve the ingestion concurrency cap that
    `docs/PRD.md` §4.1 sets at 2.

    Raises whatever the broker reported if a topic could not be created and does not
    already exist. Failing startup is the point — an app that starts without its
    topics accepts `POST /projects` and produces into nothing.
    """
    admin = AIOKafkaAdminClient(bootstrap_servers=bootstrap_servers)
    await admin.start()
    try:
        new_topics = [
            # Replication factor 1: a single-broker cluster cannot do better, and
            # the source of truth for a project's state is Postgres regardless.
            NewTopic(name=name, num_partitions=partitions, replication_factor=1)
            for name in topics
        ]
        try:
            response = await admin.create_topics(new_topics)
        except TopicAlreadyExistsError:
            # aiokafka 0.14 reports this in the response instead (see below), but
            # older and newer clients have raised it, and it is the normal path on
            # every start after the first.
            logger.debug("kafka topics already exist")
        else:
            _raise_for_topic_errors(response)
    finally:
        await admin.close()


def _raise_for_topic_errors(response: object) -> None:
    """Turn a CreateTopicsResponse's per-topic error codes into an exception.

    `AIOKafkaAdminClient.create_topics` does not raise when the broker refuses a
    topic: it returns the raw response and leaves the per-topic error codes to the
    caller. So a bare try/except around the call catches nothing, and every failure
    — a partition count the broker rejects, an authorisation failure — would look
    exactly like success.
    """
    for entry in getattr(response, "topic_errors", ()):
        topic, error_code = entry[0], entry[1]
        if error_code == _NO_ERROR:
            logger.info("kafka topic created: %s", topic)
        elif error_code == _TOPIC_ALREADY_EXISTS:
            logger.debug("kafka topic already exists: %s", topic)
        else:
            raise for_code(error_code)(f"creating Kafka topic {topic!r} failed")
