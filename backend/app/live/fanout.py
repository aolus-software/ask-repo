"""Per-connection queues for one process.

Every open `/events` stream registers a bounded queue; each event goes to all of them. A
client too slow to keep up is not given an unbounded backlog: its queue is emptied and one
`resync` marker put in its place, telling it to refetch everything. While the resync marker
is unread in a queue, further events are dropped because the refetch triggered by the marker
covers them; delivery resumes once the marker is read and the queue is empty.

`resync_all` gives every queue that marker at once (the hub reconnected, and whatever happened
while it was away was lost); `close_all` gives every queue a `close` marker, which ends its
stream and after which the queue takes nothing more (the hub lost its broker).
"""

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Final, Literal

from app.live.events import LiveEvent

RESYNC: Final = "resync"
CLOSE: Final = "close"
QUEUE_SIZE: Final = 100

QueueItem = LiveEvent | Literal["resync", "close"]


class LiveEventFanout:
    """The set of open streams in this process."""

    def __init__(self) -> None:
        self._queues: set[asyncio.Queue[QueueItem]] = set()
        self._in_resync: set[int] = set()  # Track queue IDs that have RESYNC
        # Queues holding an unread `close`. Nothing is put on them again: a later delivery
        # overflowing the queue would otherwise drain the `close` and replace it with a
        # `resync`, and a stream told to end would carry on instead.
        self._closed: set[int] = set()

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
            self._closed.discard(queue_id)

    def deliver(self, live_event: LiveEvent) -> None:
        """Put an event on every queue, replacing a full one's backlog with `resync`."""
        for queue in self._queues:
            queue_id = id(queue)
            if queue_id in self._closed:
                continue

            # Skip this event only if resync marker is still unread in the queue;
            # once consumed (queue empty), delivery resumes because the refetch covered it.
            if queue_id in self._in_resync:
                if not queue.empty():
                    continue  # resync still unread; this event is covered by its refetch
                self._in_resync.discard(queue_id)

            try:
                queue.put_nowait(live_event)
            except asyncio.QueueFull:
                while not queue.empty():
                    queue.get_nowait()
                queue.put_nowait(RESYNC)
                self._in_resync.add(queue_id)

    def resync_all(self) -> None:
        """Tell every open stream to refetch everything.

        Used when the broker connection was lost and regained: events that happened
        during the gap were never delivered, so every subscriber needs the same
        `resync` marker a slow reader would have gotten on its own.
        """
        for queue in self._queues:
            queue_id = id(queue)
            if queue_id in self._closed:
                continue
            if queue_id in self._in_resync and not queue.empty():
                continue  # already carrying an unread resync
            # The refetch a resync triggers covers whatever is still queued, so the
            # backlog goes, exactly as on overflow. Synchronous: nothing can refill the
            # queue between the drain and the put.
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(RESYNC)
            self._in_resync.add(queue_id)

    def close_all(self) -> None:
        """Drain every open queue and put `close`, ending each stream.

        Called when the broker connection is lost for good (from this process's
        point of view) so open streams stop polling a hub that will never deliver
        again, and their clients reconnect, get `503`, and fall back to polling.
        """
        for queue in self._queues:
            while not queue.empty():
                queue.get_nowait()
            queue.put_nowait(CLOSE)  # just emptied, and nothing awaits between the two
            self._closed.add(id(queue))
            self._in_resync.discard(id(queue))
