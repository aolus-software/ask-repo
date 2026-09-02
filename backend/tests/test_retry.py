"""Waiting out a delay in a log that has no delay primitive.

`seconds_until_due` is the arithmetic; everything below it is the mechanism, and the
mechanism is where the cost of being wrong lives. A consumer that sleeps through its
own delay is evicted from the group on every long retry. One that commits before
re-producing drops the retry. One that commits the whole assignment acknowledges
retries it never handed back. None of those show up in the arithmetic.

The broker is faked (`tests.fakes.FakeConsumer`) and so is the clock, so a ten-minute
rung costs no real time. What is *not* faked is the wiring: `_subscribe` is the real
one, so the rebalance listener under test is the one that ships.
"""

import uuid

import pytest
from aiokafka import TopicPartition

from app.config import get_settings
from app.queue import retry as retry_module
from app.queue.consumer import _RepauseOnRebalance
from app.queue.protocol import InMemoryIngestionQueue, TopicProducer
from app.queue.retry import RetryConsumer, seconds_until_due
from app.queue.topics import INGEST_TOPIC, RETRY_TOPICS, IngestionMessage, JobMessage
from tests.fakes import FakeConsumer, record_for

RETRY_TOPIC = RETRY_TOPICS[0][0]


def message(not_before_ms: int, *, attempt: int = 1) -> IngestionMessage:
    return IngestionMessage(
        project_id=uuid.uuid4(),
        job_id=uuid.uuid4(),
        attempt=attempt,
        not_before_ms=not_before_ms,
        original_topic=INGEST_TOPIC,
    )


class Clock:
    """A hand-cranked `_now_ms`, advancing a fixed step per read.

    The wait loop consults the clock once per poll, so a step turns "hold for three
    minutes" into "hold for three polls" and the test runs in milliseconds.
    """

    def __init__(self, *, start_ms: int = 0, step_ms: int = 0) -> None:
        self.now_ms = start_ms
        self.step_ms = step_ms
        self.reads = 0

    def __call__(self) -> int:
        self.reads += 1
        value = self.now_ms
        self.now_ms += self.step_ms
        return value


class ExplodingProducer:
    """A `TopicProducer` whose broker is down."""

    async def produce_to(self, topic: str, message: JobMessage) -> None:
        raise RuntimeError("broker unreachable")


def build(producer: TopicProducer | None = None, *, topic: str = RETRY_TOPIC) -> RetryConsumer:
    """A `RetryConsumer` on this suite's standard wiring."""
    return RetryConsumer(
        settings=get_settings(),
        producer=producer if producer is not None else InMemoryIngestionQueue(),
        topic=topic,
    )


# --- the arithmetic -------------------------------------------------------------


def test_a_future_message_reports_the_remaining_wait() -> None:
    assert seconds_until_due(message(60_000), now_ms=0) == 60.0


def test_a_due_message_reports_zero() -> None:
    assert seconds_until_due(message(1_000), now_ms=5_000) == 0.0


def test_an_exactly_due_message_reports_zero() -> None:
    assert seconds_until_due(message(5_000), now_ms=5_000) == 0.0


# --- releasing a message back onto the ingest topic ------------------------------


async def test_a_due_message_is_forwarded_unchanged_and_committed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The job id was minted when the failure was routed; re-minting it here would
    make `ProjectRepository.claim` treat the retry as a message it has already seen."""
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=10_000))
    partition = TopicPartition(RETRY_TOPIC, 0)
    consumer = FakeConsumer({partition})
    producer = InMemoryIngestionQueue()
    original = message(5_000)

    await build(producer)._release(consumer, partition, record_for(original, offset=7))

    assert producer.produced == [(get_settings().kafka_ingest_topic, original)]
    assert consumer.committed == [{partition: 8}]


async def test_a_message_not_yet_due_is_held_until_it_is(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The point of the whole module: the delay is served by polling, not sleeping.

    A consumer that slept for ten minutes would miss `max.poll.interval.ms` and be
    thrown out of the group, taking a rebalance on every long retry.
    """
    clock = Clock(start_ms=0, step_ms=1_000)
    monkeypatch.setattr(retry_module, "_now_ms", clock)
    partition = TopicPartition(RETRY_TOPIC, 0)
    consumer = FakeConsumer({partition})
    producer = InMemoryIngestionQueue()

    await build(producer)._release(consumer, partition, record_for(message(3_000)))

    # Three seconds of delay at one second per poll: it stayed alive through the wait
    # rather than blocking on it.
    assert consumer.keep_alive_polls == 3
    assert len(producer.produced) == 1


async def test_nothing_is_consumed_while_a_message_is_held(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Every assigned partition is paused, not just the held one.

    What a keep-alive poll returns is discarded. A sibling partition left running
    would have its retries read and thrown away — delayed jobs silently lost.
    """
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=0, step_ms=1_000))
    held, sibling = TopicPartition(RETRY_TOPIC, 0), TopicPartition(RETRY_TOPIC, 1)
    consumer = FakeConsumer({held, sibling})

    await build()._release(consumer, held, record_for(message(3_000)))

    assert consumer.keep_alive_polls > 0
    assert consumer.delivered_during_job == [], (
        "the keep-alive poll returned records it would have discarded"
    )


async def test_the_pause_is_reapplied_after_a_rebalance(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A rebalance rebuilds the assignment un-paused, reopening the window above."""
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=0, step_ms=1_000))
    held = TopicPartition(RETRY_TOPIC, 0)
    rebalanced = False

    async def on_poll() -> None:
        nonlocal rebalanced
        if not rebalanced:
            rebalanced = True
            await consumer.rebalance_to({held})

    consumer = FakeConsumer({held}, on_poll=on_poll)
    subject = build()
    # The real subscribe call, so the listener under test is the shipped one.
    subject._subscribe(consumer)

    await subject._release(consumer, held, record_for(message(4_000)))

    assert rebalanced
    assert consumer.delivered_during_job == []


async def test_losing_the_partition_mid_hold_does_not_commit_or_raise(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The offset is not ours to move any more; whoever holds it now gets the record
    again, and the duplicate costs one refused claim.

    `resume` and `commit` both raise for a partition we no longer hold, and either
    escaping would end the polling loop for every other retry on this rung.
    """
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=0, step_ms=1_000))
    lost, kept = TopicPartition(RETRY_TOPIC, 0), TopicPartition(RETRY_TOPIC, 1)
    taken = False

    async def on_poll() -> None:
        nonlocal taken
        if not taken:
            taken = True
            await consumer.rebalance_to({kept})

    consumer = FakeConsumer({lost, kept}, on_poll=on_poll)
    producer = InMemoryIngestionQueue()

    await build(producer)._release(consumer, lost, record_for(message(3_000)))

    assert consumer.committed == []
    # Still handed back: a duplicate is cheap, a dropped retry is not.
    assert len(producer.produced) == 1


async def test_the_commit_is_scoped_to_the_held_partition(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A bare `commit()` advances every assigned partition to its current position,
    acknowledging retries this consumer never re-produced."""
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=10_000))
    held, sibling = TopicPartition(RETRY_TOPIC, 0), TopicPartition(RETRY_TOPIC, 1)
    consumer = FakeConsumer({held, sibling})

    await build()._release(consumer, held, record_for(message(0), offset=41))

    assert consumer.committed == [{held: 42}]


async def test_an_unparseable_record_is_committed_past_and_never_forwarded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """No amount of waiting fixes a malformed record, and leaving the offset put makes
    it a wall that blocks every retry queued behind it."""
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=0))
    partition = TopicPartition(RETRY_TOPIC, 0)
    consumer = FakeConsumer({partition})
    producer = InMemoryIngestionQueue()

    class Malformed:
        value = b"{not json"
        offset = 3

    await build(producer)._release(consumer, partition, Malformed())

    assert consumer.committed == [{partition: 4}]
    assert producer.produced == []


# --- surviving a bad record ------------------------------------------------------


async def test_a_produce_failure_leaves_the_offset_put(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Committing anyway would acknowledge a retry that never went back."""
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=10_000))
    monkeypatch.setattr(retry_module, "ERROR_BACKOFF_SECONDS", 0)
    partition = TopicPartition(RETRY_TOPIC, 0)
    consumer = FakeConsumer({partition})

    await build(ExplodingProducer())._release_guarded(consumer, partition, record_for(message(0)))

    assert consumer.committed == []


async def test_one_failing_record_does_not_end_the_rung(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A consumer that dies on one record restarts, re-reads the same uncommitted
    offset, and dies again — taking every retry behind it with it."""
    monkeypatch.setattr(retry_module, "_now_ms", Clock(start_ms=10_000))
    monkeypatch.setattr(retry_module, "ERROR_BACKOFF_SECONDS", 0)
    partition = TopicPartition(RETRY_TOPIC, 0)
    consumer = FakeConsumer({partition})

    # Absorbed rather than propagated: `run()`'s loop must outlive one bad record.
    await build(ExplodingProducer())._release_guarded(consumer, partition, record_for(message(0)))


# --- wiring ----------------------------------------------------------------------


async def test_subscribe_attaches_the_repause_listener() -> None:
    """The listener is what closes the rebalance window, and a consumer subscribed
    without one loses retries silently rather than loudly."""
    consumer = FakeConsumer({TopicPartition(RETRY_TOPIC, 0)})

    build()._subscribe(consumer)

    assert isinstance(consumer.listener, _RepauseOnRebalance)


async def test_each_rung_gets_its_own_consumer_group() -> None:
    """A shared group would drag every rung into one rebalance, so a ten-minute hold
    on one would stall the one-minute rung behind it."""
    groups = {f"{get_settings().kafka_consumer_group}-{topic}" for topic, _ in RETRY_TOPICS}

    assert len(groups) == len(RETRY_TOPICS)
