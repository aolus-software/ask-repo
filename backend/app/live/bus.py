"""The in-memory stand-in for Kafka: publisher and hub in one object.

Route, service and staging tests use it the way `InMemoryIngestionQueue` stands in for the
job queue, so nothing needs a broker. Events submitted are delivered straight to this
process's open streams and recorded in `published`.
"""

import asyncio
from collections.abc import Sequence
from contextlib import AbstractAsyncContextManager

from app.live.events import LiveEvent
from app.live.fanout import LiveEventFanout, QueueItem


class LiveEventHub:
    """What the `/events` route needs from a hub. Implemented by the Kafka hub and the bus."""

    @property
    def available(self) -> bool:
        raise NotImplementedError

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        raise NotImplementedError


class InMemoryLiveEventBus(LiveEventHub):
    """Publisher and hub for tests."""

    def __init__(self) -> None:
        self.published: list[LiveEvent] = []
        self._available = True
        self._fanout = LiveEventFanout()

    @property
    def available(self) -> bool:
        return self._available

    @available.setter
    def available(self, value: bool) -> None:
        self._available = value

    def subscribe(self) -> AbstractAsyncContextManager[asyncio.Queue[QueueItem]]:
        return self._fanout.subscribe()

    def submit(self, events: Sequence[LiveEvent]) -> None:
        for live_event in events:
            self.published.append(live_event)
            self._fanout.deliver(live_event)

    def close_all(self) -> None:
        """Simulate the broker connection being lost for good: end every open stream."""
        self._fanout.close_all()
