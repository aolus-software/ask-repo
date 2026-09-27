"""Per-connection queues: every subscriber sees every event; a slow one gets `resync`."""

import uuid

from app.live.events import project_event
from app.live.fanout import CLOSE, QUEUE_SIZE, RESYNC, LiveEventFanout


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


async def test_resync_all_reaches_every_subscriber() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as first, fanout.subscribe() as second:
        fanout.resync_all()

        assert first.get_nowait() == RESYNC
        assert second.get_nowait() == RESYNC


async def test_resync_all_does_not_double_up_on_an_unread_resync() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as queue:
        fanout.resync_all()
        fanout.resync_all()

        assert queue.get_nowait() == RESYNC
        assert queue.empty()


async def test_close_all_reaches_every_subscriber_and_drains_first() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as first, fanout.subscribe() as second:
        fanout.deliver(project_event(uuid.uuid4()))
        fanout.close_all()

        assert first.get_nowait() == CLOSE
        assert first.empty()
        assert second.get_nowait() == CLOSE
        assert second.empty()


async def test_a_close_is_never_overwritten_by_later_deliveries() -> None:
    """A queue told to close takes nothing more: an overflow would otherwise drain the
    `close` and leave a `resync` in its place, and the stream would carry on."""
    fanout = LiveEventFanout()
    async with fanout.subscribe() as queue:
        fanout.close_all()
        for _ in range(QUEUE_SIZE + 5):
            fanout.deliver(project_event(uuid.uuid4()))
        fanout.resync_all()

        assert queue.get_nowait() == CLOSE
        assert queue.empty()


async def test_resync_all_replaces_a_backlog() -> None:
    fanout = LiveEventFanout()
    async with fanout.subscribe() as queue:
        fanout.deliver(project_event(uuid.uuid4()))
        fanout.resync_all()

        assert queue.get_nowait() == RESYNC
        assert queue.empty()
