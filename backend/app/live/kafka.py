"""Live events over Kafka: a best-effort publisher, and one group-less consumer per API process.

The consumer has no `group_id`: it assigns itself every partition of the topic and seeks to
the end, so there are no rebalances and no offset commits, and each API process receives
every event. `CLAUDE.md`'s pause-and-poll rule is about group members holding a seat through
a long job; a group-less consumer that polls continuously has no seat to lose.
"""

import asyncio
import contextlib
import logging
import time
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager
from typing import Final

from aiokafka import AIOKafkaConsumer, AIOKafkaProducer, TopicPartition
from pydantic import ValidationError

from app.live.bus import LiveEventHub
from app.live.events import LiveEvent
from app.live.fanout import LiveEventFanout, QueueItem

logger = logging.getLogger(__name__)

# Nothing reads history: the consumer starts at the end. An hour is margin, not a promise.
LIVE_TOPIC_CONFIGS: Final = {"retention.ms": "3600000"}
_RECONNECT_BACKOFF_SECONDS: Final = (1, 2, 5, 10, 30)
_STOP_TIMEOUT_SECONDS: Final = 5
# A group-less consumer that receives nothing looks identical to a healthy one with no
# traffic: neither raises. This is the interval on which liveness is checked by hand.
_HEALTH_CHECK_SECONDS: Final = 10
_HEALTH_CHECK_TIMEOUT_SECONDS: Final = 5


class KafkaLivePublisher:
    """Sends committed events. Never raises: a lost event costs a delayed screen update."""

    def __init__(self, *, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._producer: AIOKafkaProducer | None = None
        self._pending: set[asyncio.Task[None]] = set()

    async def start(self) -> None:
        """Connect to the broker."""
        self._producer = AIOKafkaProducer(bootstrap_servers=self._bootstrap_servers, acks=1)
        await self._producer.start()

    async def stop(self) -> None:
        """Wait for in-flight sends and disconnect.

        Bounded: a dead broker can make an in-flight `send_and_wait` hang past its own
        request timeout during shutdown, and shutdown must still finish. A timeout here
        means those sends are abandoned, not delivered — the same "a lost event costs a
        delayed screen update" trade-off this class already makes everywhere else.
        """
        if self._pending:
            try:
                await asyncio.wait_for(
                    asyncio.gather(*self._pending, return_exceptions=True),
                    timeout=_STOP_TIMEOUT_SECONDS,
                )
            except TimeoutError:
                logger.warning("live event publisher shutdown timed out waiting for sends")
        if self._producer is not None:
            await self._producer.stop()
            self._producer = None

    def submit(self, events: Sequence[LiveEvent]) -> None:
        """Fire-and-forget publish. Never blocks and never raises."""
        try:
            loop = asyncio.get_running_loop()
        except RuntimeError:
            logger.warning("live event dropped: no running event loop")
            return
        task = loop.create_task(self._send(list(events)))
        self._pending.add(task)
        task.add_done_callback(self._pending.discard)

    async def _send(self, events: list[LiveEvent]) -> None:
        if self._producer is None:
            for live_event in events:
                logger.warning("live event dropped: kind=%s id=%s", live_event.kind, live_event.id)
            return
        for live_event in events:
            try:
                # `send` only enqueues; the delivery outcome resolves on the future it
                # returns. `send_and_wait` is what actually surfaces a failed delivery
                # into this `except`, rather than into a future nobody reads.
                await self._producer.send_and_wait(self._topic, value=live_event.to_bytes())
            except Exception:
                logger.warning(
                    "live event publish failed: kind=%s id=%s",
                    live_event.kind,
                    live_event.id,
                    exc_info=True,
                )


class KafkaLiveEventHub(LiveEventHub):
    """One consumer for the process, fanning out to every open stream."""

    def __init__(self, *, bootstrap_servers: str, topic: str) -> None:
        self._bootstrap_servers = bootstrap_servers
        self._topic = topic
        self._fanout = LiveEventFanout()
        self._available = False
        self._task: asyncio.Task[None] | None = None

    @property
    def available(self) -> bool:
        return self._available

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()

    async def start(self) -> None:
        """Start consuming in the background. Never raises: an absent broker means
        `available` stays False and clients poll."""
        self._task = asyncio.create_task(self._run())

    async def stop(self) -> None:
        """Cancel the consumer loop and wait for it to finish."""
        if self._task is not None:
            self._task.cancel()
            with contextlib.suppress(asyncio.CancelledError):
                await self._task
            self._task = None

    def dispatch(self, raw: bytes) -> None:
        """Decode one message and deliver it. An undecodable message is logged and dropped."""
        try:
            live_event = LiveEvent.from_bytes(raw)
        except ValidationError:
            logger.warning("undecodable live event dropped")
            return
        self._fanout.deliver(live_event)

    async def _run(self) -> None:
        attempt = 0
        while True:
            consumer = AIOKafkaConsumer(bootstrap_servers=self._bootstrap_servers)
            try:
                await consumer.start()
                # `partitions_for_topic` is synchronous and reads cached metadata, which
                # is empty right after `start()`. `topics()` is the public, documented
                # call that forces a metadata fetch; without it this falls back to a
                # single assumed partition.
                await consumer.topics()
                partitions = consumer.partitions_for_topic(self._topic) or {0}
                assigned = [TopicPartition(self._topic, p) for p in partitions]
                consumer.assign(assigned)
                await consumer.seek_to_end(*assigned)
                self._available = True
                attempt = 0
                # Whatever happened while disconnected was lost: no offsets, no group,
                # nothing to replay. Every open stream needs the same `resync` a slow
                # reader would get on its own.
                self._fanout.resync_all()
                await self._consume(consumer)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("live event consumer lost the broker; retrying", exc_info=True)
            finally:
                self._available = False
                self._fanout.close_all()
                with contextlib.suppress(Exception):
                    await consumer.stop()
            delay = _RECONNECT_BACKOFF_SECONDS[min(attempt, len(_RECONNECT_BACKOFF_SECONDS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)

    async def _consume(self, consumer: AIOKafkaConsumer) -> None:
        """Read messages while periodically proving the connection is still alive.

        A group-less consumer raises nothing on its own when the broker drops: there is
        no heartbeat to miss and no rebalance to fail. Absent traffic, `getone()` alone
        would block forever without ever noticing. So this polls with a bounded wait
        and, every `_HEALTH_CHECK_SECONDS`, forces a metadata round trip
        (`consumer.topics()`) whose failure raises into `_run`'s `except Exception`.
        """
        last_health_check = time.monotonic()
        while True:
            now = time.monotonic()
            if now - last_health_check >= _HEALTH_CHECK_SECONDS:
                await asyncio.wait_for(consumer.topics(), timeout=_HEALTH_CHECK_TIMEOUT_SECONDS)
                last_health_check = now
            try:
                message = await asyncio.wait_for(consumer.getone(), timeout=_HEALTH_CHECK_SECONDS)
            except TimeoutError:
                continue
            if message.value is not None:
                self.dispatch(message.value)


class DisabledLiveEventHub(LiveEventHub):
    """`LIVE_EVENTS_ENABLED=false`: never available, so `/events` answers 503."""

    def __init__(self) -> None:
        self._fanout = LiveEventFanout()

    @property
    def available(self) -> bool:
        return False

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()
