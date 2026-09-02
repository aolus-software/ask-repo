"""The producer's contract, with aiokafka stubbed.

The real broker is exercised by the integration test in Task 20. Everything here
pins behaviour that would otherwise only be observable against a live cluster:
the produce arguments, the idempotence settings, and — the part that matters most
for the test suite — that the application lifespan opens no socket under
`APP_ENV=test`.
"""

import uuid
from typing import ClassVar, Self

import pytest
from aiokafka.errors import TopicAlreadyExistsError
from fastapi import FastAPI

from app.config import Settings, get_settings
from app.main import lifespan
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.topics import ALL_TOPICS, CHECKLIST_TOPIC, DLQ_TOPIC, INGEST_TOPIC, IngestionMessage

# Broker error codes, from the Kafka protocol. `create_topics` reports these in the
# response body rather than raising, so the producer has to read them.
TOPIC_ALREADY_EXISTS = 36
INVALID_PARTITIONS = 37


class StubProducer:
    """Stands in for AIOKafkaProducer."""

    def __init__(self, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.sent: list[tuple[str, bytes, bytes]] = []
        self.started = False

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.started = False

    async def send_and_wait(self, topic: str, value: bytes, key: bytes) -> None:
        self.sent.append((topic, value, key))


class StubResponse:
    """A CreateTopicsResponse, reduced to the field the producer reads."""

    def __init__(self, topic_errors: list[tuple[str, int, str | None]]) -> None:
        self.topic_errors = topic_errors


class StubAdminClient:
    """Stands in for AIOKafkaAdminClient.

    `error_code` is the code the broker reports for every requested topic.
    """

    instances: ClassVar[list["StubAdminClient"]] = []

    def __init__(self, *, error_code: int = 0, **kwargs: object) -> None:
        self.kwargs = kwargs
        self.error_code = error_code
        self.requested: list[object] = []
        self.started = False
        self.closed = False
        StubAdminClient.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def create_topics(self, topics: list[object]) -> StubResponse:
        self.requested = list(topics)
        names = [getattr(topic, "name", "") for topic in topics]
        return StubResponse([(name, self.error_code, None) for name in names])


class StubQueue:
    """Stands in for KafkaIngestionQueue inside the lifespan tests."""

    instances: ClassVar[list["StubQueue"]] = []

    def __init__(self, *, bootstrap_servers: str, topic: str, checklist_topic: str) -> None:
        self.bootstrap_servers = bootstrap_servers
        self.topic = topic
        self.checklist_topic = checklist_topic
        self.started = False
        self.stopped = False
        StubQueue.instances.append(self)

    async def start(self) -> None:
        self.started = True

    async def stop(self) -> None:
        self.stopped = True


class ExplodingAdminClient:
    """An admin client that fails the way an unreachable broker does."""

    def __init__(self, **kwargs: object) -> None:
        self.closed = False

    async def start(self) -> None:
        self.started = True

    async def close(self) -> None:
        self.closed = True

    async def create_topics(self, topics: list[object]) -> Self:
        raise ConnectionError("no route to broker")


def install_stub_producer(monkeypatch: pytest.MonkeyPatch) -> StubProducer:
    """Patch AIOKafkaProducer with a stub that records its construction kwargs.

    A factory rather than `lambda **kwargs: stub`: the queue's settings only exist in
    the constructor call, so a stub built before the patch never sees them.
    """
    stub = StubProducer()

    def build(**kwargs: object) -> StubProducer:
        stub.kwargs = kwargs
        return stub

    monkeypatch.setattr("app.queue.producer.AIOKafkaProducer", build)
    return stub


def message(*, attempt: int = 0) -> IngestionMessage:
    return IngestionMessage(
        project_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=attempt,
        not_before_ms=0,
        original_topic=INGEST_TOPIC,
    )


@pytest.fixture(autouse=True)
def _reset_stub_registries() -> None:
    """The stubs above record their instances on the class; keep tests independent."""
    StubAdminClient.instances.clear()
    StubQueue.instances.clear()


# --- the producer -----------------------------------------------------------------


async def test_enqueue_publishes_to_the_ingest_topic(monkeypatch: pytest.MonkeyPatch) -> None:
    stub = install_stub_producer(monkeypatch)

    queue = KafkaIngestionQueue(
        bootstrap_servers="localhost:9092", topic=INGEST_TOPIC, checklist_topic=CHECKLIST_TOPIC
    )
    await queue.start()
    sent = message()
    await queue.enqueue(sent)

    assert len(stub.sent) == 1
    topic, value, key = stub.sent[0]
    assert topic == INGEST_TOPIC
    assert IngestionMessage.from_bytes(value) == sent
    assert key == sent.key()


async def test_the_producer_is_idempotent(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without this a retried produce appends the message twice."""
    stub = install_stub_producer(monkeypatch)

    await KafkaIngestionQueue(
        bootstrap_servers="localhost:9092", topic=INGEST_TOPIC, checklist_topic=CHECKLIST_TOPIC
    ).start()

    assert stub.kwargs["enable_idempotence"] is True
    assert stub.kwargs["acks"] == "all"


async def test_produce_to_targets_the_topic_it_is_given(monkeypatch: pytest.MonkeyPatch) -> None:
    """The retry and DLQ paths publish to a topic that is not the queue's own."""
    stub = install_stub_producer(monkeypatch)

    queue = KafkaIngestionQueue(
        bootstrap_servers="localhost:9092", topic=INGEST_TOPIC, checklist_topic=CHECKLIST_TOPIC
    )
    await queue.start()
    await queue.produce_to(DLQ_TOPIC, message(attempt=3))

    assert [topic for topic, _, _ in stub.sent] == [DLQ_TOPIC]


async def test_enqueue_before_start_is_a_programming_error() -> None:
    queue = KafkaIngestionQueue(
        bootstrap_servers="localhost:9092", topic=INGEST_TOPIC, checklist_topic=CHECKLIST_TOPIC
    )
    with pytest.raises(RuntimeError, match="not started"):
        await queue.enqueue(message())


async def test_enqueue_after_stop_is_a_programming_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Producing through a stopped queue must fail rather than silently drop a job."""
    stub = install_stub_producer(monkeypatch)

    queue = KafkaIngestionQueue(
        bootstrap_servers="localhost:9092", topic=INGEST_TOPIC, checklist_topic=CHECKLIST_TOPIC
    )
    await queue.start()
    await queue.stop()

    assert stub.started is False
    with pytest.raises(RuntimeError, match="not started"):
        await queue.enqueue(message())


async def test_stopping_a_queue_that_never_started_is_a_no_op() -> None:
    """The lifespan's `finally` runs even when start failed."""
    await KafkaIngestionQueue(
        bootstrap_servers="localhost:9092", topic=INGEST_TOPIC, checklist_topic=CHECKLIST_TOPIC
    ).stop()


# --- topic creation ---------------------------------------------------------------


async def test_ensure_topics_creates_every_topic_with_the_configured_partitions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Auto-created topics get one partition, which would halve the concurrency cap."""
    monkeypatch.setattr("app.queue.producer.AIOKafkaAdminClient", StubAdminClient)

    await ensure_topics(bootstrap_servers="localhost:9092", partitions=2)

    admin = StubAdminClient.instances[0]
    assert admin.started is True
    assert admin.closed is True
    assert [topic.name for topic in admin.requested] == list(ALL_TOPICS)  # type: ignore[attr-defined]  # NewTopic
    assert {topic.num_partitions for topic in admin.requested} == {2}  # type: ignore[attr-defined]  # NewTopic
    assert {topic.replication_factor for topic in admin.requested} == {1}  # type: ignore[attr-defined]  # NewTopic


async def test_ensure_topics_tolerates_topics_that_already_exist(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every start after the first reports "already exists" for every topic."""
    monkeypatch.setattr(
        "app.queue.producer.AIOKafkaAdminClient",
        lambda **kwargs: StubAdminClient(error_code=TOPIC_ALREADY_EXISTS, **kwargs),
    )

    await ensure_topics(bootstrap_servers="localhost:9092", partitions=2)

    assert StubAdminClient.instances[0].closed is True


class RaisingAdminClient(StubAdminClient):
    """A client that *raises* already-exists instead of reporting it in the response.

    aiokafka 0.14 reports per-topic outcomes in `topic_errors` and never raises here,
    so `ensure_topics` handles both shapes. This pins the branch that would otherwise
    be unreachable and therefore untested -- `aiokafka>=0.12.0` is an open-ended pin,
    and a client that went back to raising would fail startup on every restart after
    the first.
    """

    async def create_topics(self, topics: list[object]) -> StubResponse:
        self.requested = list(topics)
        raise TopicAlreadyExistsError("topic already exists")


async def test_ensure_topics_tolerates_a_client_that_raises_already_exists(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The other shape of the same normal path. Must not fail startup, and must
    still close the admin client."""
    monkeypatch.setattr(
        "app.queue.producer.AIOKafkaAdminClient",
        lambda **kwargs: RaisingAdminClient(**kwargs),
    )

    await ensure_topics(bootstrap_servers="localhost:9092", partitions=2)

    assert RaisingAdminClient.instances[-1].closed is True


async def test_ensure_topics_raises_on_any_other_broker_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A swallowed failure here starts an app that produces into topics that are not
    there. `create_topics` reports per-topic failures in the response rather than
    raising, so this is the only thing standing between a rejected topic and a silent
    startup."""
    monkeypatch.setattr(
        "app.queue.producer.AIOKafkaAdminClient",
        lambda **kwargs: StubAdminClient(error_code=INVALID_PARTITIONS, **kwargs),
    )

    with pytest.raises(Exception, match=INGEST_TOPIC):
        await ensure_topics(bootstrap_servers="localhost:9092", partitions=2)

    assert StubAdminClient.instances[0].closed is True


async def test_ensure_topics_closes_the_admin_client_when_the_broker_is_unreachable(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Otherwise a failed startup leaks the admin client's connection."""
    clients: list[ExplodingAdminClient] = []

    def build(**kwargs: object) -> ExplodingAdminClient:
        client = ExplodingAdminClient(**kwargs)
        clients.append(client)
        return client

    monkeypatch.setattr("app.queue.producer.AIOKafkaAdminClient", build)

    with pytest.raises(ConnectionError):
        await ensure_topics(bootstrap_servers="localhost:9092", partitions=2)

    assert clients[0].closed is True


# --- the lifespan -----------------------------------------------------------------


async def test_the_lifespan_touches_no_broker_in_the_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The whole suite builds the real app and there is no broker behind
    `localhost:9092`. Without this guard the lifespan blocks on the bootstrap address
    rather than failing, so the suite hangs instead of reporting anything."""

    def forbidden(**kwargs: object) -> None:
        raise AssertionError("the lifespan must not reach Kafka when APP_ENV=test")

    monkeypatch.setattr("app.main.ensure_topics", forbidden)
    monkeypatch.setattr("app.main.KafkaIngestionQueue", forbidden)

    assert get_settings().app_env == "test"
    application = FastAPI()
    async with lifespan(application):
        pass

    assert getattr(application.state, "ingestion_queue", None) is None


async def test_the_lifespan_owns_the_producer_outside_the_test_environment(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """`get_ingestion_queue` reads `app.state.ingestion_queue`, so the attribute name
    is a contract with `app/api/routes/projects.py`."""
    settings = Settings(
        app_env="development",
        kafka_bootstrap_servers="broker:9092",
        kafka_ingest_topic=INGEST_TOPIC,
        kafka_ingest_partitions=2,
    )
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    ensured: list[tuple[str, int]] = []

    async def record_ensure_topics(
        *, bootstrap_servers: str, partitions: int, topics: tuple[str, ...] = ()
    ) -> None:
        ensured.append((bootstrap_servers, partitions))

    monkeypatch.setattr("app.main.ensure_topics", record_ensure_topics)
    monkeypatch.setattr("app.main.KafkaIngestionQueue", StubQueue)

    application = FastAPI()
    async with lifespan(application):
        queue = StubQueue.instances[0]
        assert application.state.ingestion_queue is queue
        assert queue.started is True
        assert queue.stopped is False
        assert queue.bootstrap_servers == "broker:9092"
        assert queue.topic == INGEST_TOPIC

    # The ingest call, then the checklist family (spec 4.1 / `app/queue/checklist.py`).
    assert ensured == [("broker:9092", 2), ("broker:9092", settings.kafka_checklist_partitions)]
    assert StubQueue.instances[0].stopped is True


async def test_the_lifespan_stops_the_producer_when_the_app_raises(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A crash during serving must still flush and close the producer."""
    settings = Settings(app_env="development")
    monkeypatch.setattr("app.main.get_settings", lambda: settings)

    async def noop(
        *, bootstrap_servers: str, partitions: int, topics: tuple[str, ...] = ()
    ) -> None:
        return None

    monkeypatch.setattr("app.main.ensure_topics", noop)
    monkeypatch.setattr("app.main.KafkaIngestionQueue", StubQueue)

    application = FastAPI()
    with pytest.raises(RuntimeError, match="serving failed"):
        async with lifespan(application):
            raise RuntimeError("serving failed")

    assert StubQueue.instances[0].stopped is True
