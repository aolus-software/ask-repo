"""Topic names and the ingestion message format.

Kafka has no delayed-delivery primitive, so the delay is built from topics: a failed
job moves to a fixed-delay retry topic, and a consumer there waits until the message
is due before re-producing it. `RETRY_TOPICS` is ordered by attempt.
"""

import json
import uuid
from dataclasses import asdict, dataclass
from typing import Protocol, runtime_checkable

INGEST_TOPIC = "askrepo.ingest.requested"
DLQ_TOPIC = "askrepo.ingest.dlq"

# (topic, delay_seconds), consulted in order by attempt number.
RETRY_TOPICS: tuple[tuple[str, int], ...] = (
    ("askrepo.ingest.retry.1m", 60),
    ("askrepo.ingest.retry.10m", 600),
)

ALL_TOPICS = (INGEST_TOPIC, *[topic for topic, _ in RETRY_TOPICS], DLQ_TOPIC)


@dataclass(frozen=True, slots=True)
class IngestionMessage:
    """One request to index one project.

    `job_id` is minted per enqueue and recorded on the project when the run finishes.
    It is what lets the worker tell "a new reindex was requested" from "an old message
    arrived twice" — see `ProjectRepository.claim`.
    """

    project_id: uuid.UUID
    job_id: uuid.UUID
    attempt: int
    not_before_ms: int
    original_topic: str

    def to_bytes(self) -> bytes:
        """Serialise for the wire.

        JSON rather than a binary codec: these are a handful of messages a day, and
        someone debugging the DLQ should be able to read one.
        """
        payload = asdict(self)
        payload["project_id"] = str(self.project_id)
        payload["job_id"] = str(self.job_id)
        return json.dumps(payload).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "IngestionMessage":
        """Parse a message off the wire."""
        payload = json.loads(raw)
        return cls(
            project_id=uuid.UUID(payload["project_id"]),
            job_id=uuid.UUID(payload["job_id"]),
            attempt=int(payload["attempt"]),
            not_before_ms=int(payload["not_before_ms"]),
            original_topic=str(payload["original_topic"]),
        )

    def key(self) -> bytes:
        """Partition key.

        Keying by project puts a project's messages on one partition *of one topic*,
        so ordering holds within the ingest topic. It does **not** prevent two
        concurrent attempts: the retry ladder crosses topics, so a queued retry and a
        fresh reindex can be delivered at the same moment on different partitions.
        `ProjectRepository.claim` is the only thing that stops them both running —
        do not treat the lease as belt-and-braces on top of this.
        """
        return str(self.project_id).encode()


def next_destination(*, attempt: int, max_attempts: int) -> tuple[str, int]:
    """Where a job goes after failing its `attempt`-th try, and how long it waits.

    Returns the DLQ with a zero delay once the attempts are spent.
    """
    if attempt >= max_attempts - 1 or attempt >= len(RETRY_TOPICS):
        return DLQ_TOPIC, 0
    return RETRY_TOPICS[attempt]


@runtime_checkable
class JobMessage(Protocol):
    """What the ladder needs of a job message, whatever kind of job it is.

    `RetryConsumer` and `TopicProducer` are written against this rather than against
    `IngestionMessage`, so one delay ladder serves both ingestion and checklist
    generation instead of two near-copies drifting apart.
    """

    # Declared as read-only properties, not plain attributes: both dataclasses below
    # are frozen, and mypy treats a frozen dataclass field as read-only. A plain
    # attribute here would demand a settable one and neither implementation would
    # structurally satisfy the protocol.
    @property
    def attempt(self) -> int: ...

    @property
    def not_before_ms(self) -> int: ...

    @property
    def original_topic(self) -> str: ...

    def to_bytes(self) -> bytes:
        """Serialise for the wire."""
        ...

    def key(self) -> bytes:
        """Partition key."""
        ...


CHECKLIST_TOPIC = "askrepo.checklist.generate"
CHECKLIST_DLQ_TOPIC = "askrepo.checklist.dlq"

# Its own ladder, not ingestion's. A stuck generation retrying for eleven minutes must
# not sit in the queue a project reindex is waiting in.
CHECKLIST_RETRY_TOPICS: tuple[tuple[str, int], ...] = (
    ("askrepo.checklist.retry.1m", 60),
    ("askrepo.checklist.retry.10m", 600),
)

ALL_CHECKLIST_TOPICS = (
    CHECKLIST_TOPIC,
    *[topic for topic, _ in CHECKLIST_RETRY_TOPICS],
    CHECKLIST_DLQ_TOPIC,
)


@dataclass(frozen=True, slots=True)
class ChecklistJobMessage:
    """One request to generate one module's checklist.

    `job_id` is minted per enqueue and recorded on the module when the run finishes.
    It is what lets the worker tell "a new generation was requested" from "an old
    message arrived twice" -- see `ChecklistModuleRepository.claim`.
    """

    module_id: uuid.UUID
    job_id: uuid.UUID
    attempt: int
    not_before_ms: int
    original_topic: str

    def to_bytes(self) -> bytes:
        """Serialise for the wire."""
        payload = asdict(self)
        payload["module_id"] = str(self.module_id)
        payload["job_id"] = str(self.job_id)
        return json.dumps(payload).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "ChecklistJobMessage":
        """Parse a message off the wire."""
        payload = json.loads(raw)
        return cls(
            module_id=uuid.UUID(payload["module_id"]),
            job_id=uuid.UUID(payload["job_id"]),
            attempt=int(payload["attempt"]),
            not_before_ms=int(payload["not_before_ms"]),
            original_topic=str(payload["original_topic"]),
        )

    def key(self) -> bytes:
        """Partition key.

        Orders one module's messages within one topic. It does **not** deduplicate:
        the retry ladder crosses topics, so a queued retry and a fresh generation can
        arrive at the same moment on different partitions. The lease on the module row
        is what stops them both running.
        """
        return str(self.module_id).encode()


def checklist_next_destination(*, attempt: int, max_attempts: int) -> tuple[str, int]:
    """Where a generation goes after failing, and how long it waits.

    Returns the checklist DLQ with a zero delay once the attempts are spent.
    """
    if attempt >= max_attempts - 1 or attempt >= len(CHECKLIST_RETRY_TOPICS):
        return CHECKLIST_DLQ_TOPIC, 0
    return CHECKLIST_RETRY_TOPICS[attempt]


MOCK_DATA_TOPIC = "askrepo.mock-data.generate"
MOCK_DATA_DLQ_TOPIC = "askrepo.mock-data.dlq"

# Its own ladder, like the checklist's: a stuck mock-data generation must not sit in
# the queue a project reindex or a checklist run is waiting in.
MOCK_DATA_RETRY_TOPICS: tuple[tuple[str, int], ...] = (
    ("askrepo.mock-data.retry.1m", 60),
    ("askrepo.mock-data.retry.10m", 600),
)

ALL_MOCK_DATA_TOPICS = (
    MOCK_DATA_TOPIC,
    *[topic for topic, _ in MOCK_DATA_RETRY_TOPICS],
    MOCK_DATA_DLQ_TOPIC,
)


@dataclass(frozen=True, slots=True)
class MockDataJobMessage:
    """One request to generate one module's mock dataset.

    `job_id` is minted per enqueue and recorded on the dataset when the run finishes --
    see `MockDataDatasetRepository.claim`, the same "new request vs redelivery" test
    `ChecklistModuleRepository.claim` runs. `count` rides on the message rather than
    being re-read from a request at generation time: the job may run long after the
    request that queued it, on a worker that never saw the original HTTP body.
    """

    dataset_id: uuid.UUID
    job_id: uuid.UUID
    attempt: int
    not_before_ms: int
    original_topic: str
    count: int

    def to_bytes(self) -> bytes:
        """Serialise for the wire."""
        payload = asdict(self)
        payload["dataset_id"] = str(self.dataset_id)
        payload["job_id"] = str(self.job_id)
        return json.dumps(payload).encode()

    @classmethod
    def from_bytes(cls, raw: bytes) -> "MockDataJobMessage":
        """Parse a message off the wire."""
        payload = json.loads(raw)
        return cls(
            dataset_id=uuid.UUID(payload["dataset_id"]),
            job_id=uuid.UUID(payload["job_id"]),
            attempt=int(payload["attempt"]),
            not_before_ms=int(payload["not_before_ms"]),
            original_topic=str(payload["original_topic"]),
            count=int(payload["count"]),
        )

    def key(self) -> bytes:
        """Partition key. Orders one dataset's messages within one topic; the lease on
        the dataset row is what stops two runs racing, not this."""
        return str(self.dataset_id).encode()


def mock_data_next_destination(*, attempt: int, max_attempts: int) -> tuple[str, int]:
    """Where a mock-data generation goes after failing, and how long it waits."""
    if attempt >= max_attempts - 1 or attempt >= len(MOCK_DATA_RETRY_TOPICS):
        return MOCK_DATA_DLQ_TOPIC, 0
    return MOCK_DATA_RETRY_TOPICS[attempt]
