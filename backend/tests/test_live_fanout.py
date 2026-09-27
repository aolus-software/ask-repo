"""Per-connection queues: every subscriber sees every event; a slow one gets `resync`."""

import uuid

from app.live.events import project_event
from app.live.fanout import QUEUE_SIZE, RESYNC, LiveEventFanout


async def test_every_subscriber_receives_each_event() -> None:
    fanout = LiveEventFanout()
    event = project_event(uuid.uuid4())
    async with fanout.subscribe() as first, fanout.subscribe() as second:
        fanout.deliver(event)
        assert first.get_nowait() == event
        assert second.get_nowait() == event


async def test_a_full_queue_is_replaced_by_one_resync() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as queue:
        for _ in range(QUEUE_SIZE + 5):
            fanout.deliver(project_event(uuid.uuid4()))
        assert queue.get_nowait() == RESYNC
        assert queue.empty()


async def test_leaving_the_context_unsubscribes() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe():
        assert fanout.subscriber_count == 1
    assert fanout.subscriber_count == 0


async def test_delivery_resumes_once_the_resync_marker_is_read() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as queue:
        for _ in range(QUEUE_SIZE + 1):
            fanout.deliver(project_event(uuid.uuid4()))
        assert queue.get_nowait() == RESYNC

        later = project_event(uuid.uuid4())
        fanout.deliver(later)

        assert queue.get_nowait() == later
