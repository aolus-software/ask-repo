"""Turning a fixed-delay topic into delayed delivery.

Kafka has no delay primitive. What it has instead is order: every message on a
fixed-delay topic was appended when its delay started, so within a partition the head
is always the earliest-due message and nothing behind it can come due sooner. That is
what makes "hold the head until it is due" a schedule rather than a guess.

So this consumer reads the head, holds it, re-produces it to the main ingest topic and
only then commits. It never seeks past a message and never commits one it has not
re-produced: while the delay is running, the uncommitted offset is the only record
that the retry is still owed.

**Holding is not sleeping.** The longest rung of the ladder is ten minutes
(`RETRY_TOPICS`), and Kafka evicts a member that has not called `poll` within
`max.poll.interval.ms` — five minutes by default. A consumer that slept through its
own delay would be thrown out of the group on every long retry, taking a rebalance
each time. It keeps polling with every assigned partition paused instead: a paused
partition returns nothing, the member stays alive, and the wait costs one empty fetch
per second.

**The message is forwarded unchanged.** The job id it carries was minted fresh for
this attempt when the failure was routed (`consumer._route_failure`), because
`ProjectRepository.claim` refuses a job id it has already recorded. Re-keying or
re-idding it here would either undo that or hide a duplicate delivery from the claim.
"""

import asyncio
import logging
import time

from aiokafka import AIOKafkaConsumer, ConsumerRecord, TopicPartition
from aiokafka.errors import CommitFailedError, IllegalStateError

from app.config import Settings

# Package-private import, deliberately shared rather than copied: the listener is the
# subtle half of surviving a rebalance, and a second copy of it would be a second
# thing to get wrong. It also has to subclass an untyped aiokafka base, which
# `pyproject.toml` permits in exactly one module.
from app.queue.consumer import _RepauseOnRebalance
from app.queue.protocol import TopicProducer
from app.queue.topics import IngestionMessage

logger = logging.getLogger(__name__)

POLL_TIMEOUT_MS = 1000
# A brief pause after an unhandled error, so a persistent broker fault backs off
# instead of spinning the loop at full speed.
ERROR_BACKOFF_SECONDS = 1.0


def seconds_until_due(message: IngestionMessage, *, now_ms: int) -> float:
    """How long to wait before this message may be re-produced. Never negative."""
    return max(0.0, (message.not_before_ms - now_ms) / 1000)


def _now_ms() -> int:
    """Wall-clock time in epoch milliseconds, matching `not_before_ms`.

    A named function rather than an inline expression so a test can drive the wait
    loop without spending the delay in real time.
    """
    return int(time.time() * 1000)


class RetryConsumer:
    """Drains one retry topic back into the main ingest topic, on schedule."""

    def __init__(self, *, settings: Settings, producer: TopicProducer, topic: str) -> None:
        self.settings = settings
        self.producer = producer
        self.topic = topic
        # Read by the rebalance listener: a partition handed to us while a message is
        # being held must arrive paused, or the keep-alive poll starts eating retries.
        self._waiting = False

    async def run(self) -> None:
        """Poll, hold until due, re-produce, commit — forever."""
        consumer = AIOKafkaConsumer(
            bootstrap_servers=self.settings.kafka_bootstrap_servers,
            # One group per rung. The rungs are independent ladders with different
            # delays, and a shared group would drag all of them into one rebalance.
            group_id=f"{self.settings.kafka_consumer_group}-{self.topic}",
            # The offset moves only after the retry has been handed back.
            enable_auto_commit=False,
            auto_offset_reset="earliest",
        )
        self._subscribe(consumer)
        await consumer.start()
        try:
            while True:
                batches = await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS, max_records=1)
                for partition, records in batches.items():
                    for record in records:
                        await self._release_guarded(consumer, partition, record)
        finally:
            await consumer.stop()

    def _subscribe(self, consumer: AIOKafkaConsumer) -> None:
        """Subscribe to this rung's topic with the rebalance listener attached.

        Separate from `run` so a test can wire a fake consumer exactly the way the real
        one is wired. The listener is load-bearing, and a test that re-implemented this
        call would stop proving it is attached.
        """
        consumer.subscribe(
            topics=[self.topic],
            listener=_RepauseOnRebalance(consumer, lambda: self._waiting),
        )

    async def _release_guarded(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        record: ConsumerRecord[bytes, bytes],
    ) -> None:
        """Hold one record, absorbing anything it raises.

        A consumer that dies on one record never makes progress: it restarts, reads the
        same uncommitted offset, and dies again — and every retry queued behind that
        record is stuck with it. Absorbing is safe because the offset stays put, so the
        record is redelivered, and a duplicate re-produce is refused downstream by
        `ProjectRepository.claim`.
        """
        try:
            await self._release(consumer, partition, record)
        except Exception:
            logger.exception("failed to release %s offset %s; continuing", partition, record.offset)
            await asyncio.sleep(ERROR_BACKOFF_SECONDS)

    async def _release(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        record: ConsumerRecord[bytes, bytes],
    ) -> None:
        """Hold the message until it is due, then send it back to the main topic."""
        try:
            message = IngestionMessage.from_bytes(record.value)
        except (TypeError, ValueError, KeyError):
            # Unparseable: no amount of waiting fixes it, and leaving the offset here
            # makes this record a wall that blocks every retry behind it. Move past it.
            logger.exception(
                "discarding unparseable record at %s offset %s", partition, record.offset
            )
            await self._commit(consumer, partition, record)
            return

        paused = self._pause_assigned(consumer)
        self._waiting = True
        try:
            await self._wait_until_due(consumer, message)
            logger.info("re-queueing project %s (attempt %d)", message.project_id, message.attempt)
            # Forwarded exactly as received — see this module's docstring on the job id.
            await self.producer.produce_to(self.settings.kafka_ingest_topic, message)
            await self._commit(consumer, partition, record)
        finally:
            self._waiting = False
            self._resume(consumer, paused)

    async def _wait_until_due(self, consumer: AIOKafkaConsumer, message: IngestionMessage) -> None:
        """Poll without consuming until the delay has elapsed.

        Everything assigned is paused, so each poll returns nothing and simply keeps
        the group membership alive — *every* partition, not just this record's, because
        what a poll returns here is discarded, and a sibling partition left running
        would have its retries read and thrown away rather than redelivered.

        Re-paused on every tick as a backstop: a rebalance rebuilds per-partition state
        un-paused. `_RepauseOnRebalance` is what closes that window properly; this
        catches an assignment gained without a callback, and `pause` on an
        already-paused partition costs nothing.

        Granularity is the poll timeout — a message comes due up to a second late,
        against delays measured in minutes.
        """
        while seconds_until_due(message, now_ms=_now_ms()) > 0:
            self._pause_assigned(consumer)
            await consumer.getmany(timeout_ms=POLL_TIMEOUT_MS)

    def _pause_assigned(self, consumer: AIOKafkaConsumer) -> list[TopicPartition]:
        """Pause every currently assigned partition, and report which those were."""
        assigned = list(consumer.assignment())
        if assigned:
            consumer.pause(*assigned)
        return assigned

    def _resume(self, consumer: AIOKafkaConsumer, paused: list[TopicPartition]) -> None:
        """Resume only what we paused *and* still hold.

        A rebalance can take a partition away mid-wait, and `resume` raises
        `IllegalStateError` for one that is no longer assigned — which would otherwise
        escape a `finally` and end the polling loop.
        """
        still_ours = [partition for partition in paused if partition in consumer.assignment()]
        if still_ours:
            consumer.resume(*still_ours)

    async def _commit(
        self,
        consumer: AIOKafkaConsumer,
        partition: TopicPartition,
        record: ConsumerRecord[bytes, bytes],
    ) -> None:
        """Move this partition's offset past the record, if it is still ours.

        Scoped to one partition: a bare `commit()` would advance every assigned
        partition to its current position, acknowledging retries this consumer has not
        re-produced and dropping them. Losing the partition mid-wait means the offset
        is not ours to move at all — whoever holds it now is handed the record again,
        and the duplicate costs one refused claim.
        """
        try:
            await consumer.commit({partition: record.offset + 1})
        except (IllegalStateError, CommitFailedError):
            logger.warning(
                "could not commit %s offset %s: the partition is no longer ours",
                partition,
                record.offset,
            )
