"""Live events over Kafka: a best-effort publisher, and one group-less consumer per API process.

The consumer has no `group_id`: it assigns itself every partition of the topic and seeks to
the end, so there are no rebalances and no offset commits, and each API process receives
every event. `CLAUDE.md`'s pause-and-poll rule is about group members holding a seat through
a long job; a group-less consumer that polls continuously has no seat to lose.
"""

import asyncio
import contextlib
import logging
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
        """Wait for in-flight sends and disconnect."""
        if self._pending:
            await asyncio.gather(*self._pending, return_exceptions=True)
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
            return
        for live_event in events:
            try:
                await self._producer.send(self._topic, value=live_event.to_bytes())
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
                async for message in consumer:
                    if message.value is not None:
                        self.dispatch(message.value)
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("live event consumer lost the broker; retrying", exc_info=True)
            finally:
                self._available = False
                with contextlib.suppress(Exception):
                    await consumer.stop()
            delay = _RECONNECT_BACKOFF_SECONDS[min(attempt, len(_RECONNECT_BACKOFF_SECONDS) - 1)]
            attempt += 1
            await asyncio.sleep(delay)


class DisabledLiveEventHub(LiveEventHub):
    """`LIVE_EVENTS_ENABLED=false`: never available, so `/events` answers 503."""

    def __init__(self) -> None:
        self._fanout = LiveEventFanout()

    @property
    def available(self) -> bool:
        return False

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()
