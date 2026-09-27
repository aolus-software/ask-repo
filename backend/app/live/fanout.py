"""Per-connection queues for one process.

Every open `/events` stream registers a bounded queue; each event goes to all of them. A
client too slow to keep up is not given an unbounded backlog: its queue is emptied and one
`resync` marker put in its place, telling it to refetch everything.
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, Literal

from app.live.events import LiveEvent

RESYNC: Final = "resync"
QUEUE_SIZE: Final = 100

QueueItem = LiveEvent | Literal["resync"]


class LiveEventFanout:
    """The set of open streams in this process."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[QueueItem]] = set()
        self._in_resync: set[int] = set()  # Track queue IDs that have RESYNC

    @property
    def subscriber_count(self) -> int:
        """How many streams are open."""
        return len(self._queues)

    @asynccontextmanager
    async def subscribe(self) -> AsyncIterator[asyncio.Queue[QueueItem]]:
        """Register a queue for the life of the `async with` block."""
        queue: asyncio.Queue[QueueItem] = asyncio.Queue(maxsize=QUEUE_SIZE)
        queue_id = id(queue)
        self._queues.add(queue)
        try:
            yield queue
        finally:
            self._queues.discard(queue)
            self._in_resync.discard(queue_id)

    def deliver(self, live_event: LiveEvent) -> None:
        """Put an event on every queue, replacing a full one's backlog with `resync`."""
        for queue in self._queues:
            queue_id = id(queue)

            # Skip queues in resync mode; they're waiting for client to reconnect
            if queue_id in self._in_resync:
                continue

            try:
                queue.put_nowait(live_event)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(RESYNC)
                self._in_resync.add(queue_id)
