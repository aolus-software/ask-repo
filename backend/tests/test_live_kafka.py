"""The Kafka hub's decoding and fan-out, without a broker."""

import asyncio
import contextlib
import logging
import uuid
from typing import Any

import pytest

from app.live import kafka as kafka_module
from app.live.events import project_event
from app.live.fanout import CLOSE, RESYNC
from app.live.kafka import DisabledLiveEventHub, KafkaLiveEventHub, KafkaLivePublisher


async def test_dispatch_decodes_and_delivers() -> None:
    hub = KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t")
    event = project_event(uuid.uuid4())
    async with hub.subscribe() as queue:
        hub.dispatch(event.to_bytes())
        assert queue.get_nowait() == event


async def test_an_undecodable_message_is_dropped() -> None:
    hub = KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t")
    async with hub.subscribe() as queue:
        hub.dispatch(b"not json")
        assert queue.empty()


def test_a_hub_is_unavailable_until_it_connects() -> None:
    assert KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t").available is False
    assert DisabledLiveEventHub().available is False


async def test_submitting_before_start_logs_and_does_not_raise(
    caplog: pytest.LogCaptureFixture,
) -> None:
    """`submit` before `start()` (or after `stop()` nulled the producer) must not
    raise, and the dropped event must not vanish silently."""
    publisher = KafkaLivePublisher(bootstrap_servers="unused:9092", topic="t")
    event = project_event(uuid.uuid4())
    with caplog.at_level(logging.WARNING, logger="app.live.kafka"):
        publisher.submit([event])
        await publisher.stop()

    assert any(
        "live event dropped" in record.getMessage() and str(event.id) in record.getMessage()
        for record in caplog.records
    )


class _StubConsumer:
    """Connects once, then fails its next health check — driving the loss path (F3)
    without a real broker."""

    def __init__(self, *args: object, **kwargs: object) -> None:
        self._topics_calls = 0

    async def start(self) -> None:
        return None

    async def topics(self) -> set[str]:
        self._topics_calls += 1
        if self._topics_calls > 1:
            raise RuntimeError("broker gone")
        return {"t"}

    def partitions_for_topic(self, topic: str) -> set[int]:
        return {0}

    def assign(self, partitions: object) -> None:
        return None

    async def seek_to_end(self, *partitions: object) -> None:
        return None

    async def getone(self) -> Any:
        # Long enough that the health check, not this call, is what notices the loss.
        await asyncio.sleep(10)
        raise AssertionError("getone should have been cancelled by the health check")

    async def stop(self) -> None:
        return None


async def test_the_loss_path_closes_every_open_stream(monkeypatch: pytest.MonkeyPatch) -> None:
    """A group-less consumer raises nothing on its own when the broker drops (F3): the
    periodic health check is what has to notice, and noticing has to end every open
    stream rather than leave it polling a hub that will never deliver again."""
    monkeypatch.setattr(kafka_module, "_HEALTH_CHECK_SECONDS", 0.05)
    monkeypatch.setattr(kafka_module, "_RECONNECT_BACKOFF_SECONDS", (0.01,))
    monkeypatch.setattr(kafka_module, "AIOKafkaConsumer", _StubConsumer)

    hub = kafka_module.KafkaLiveEventHub(bootstrap_servers="unused:9092", topic="t")
    async with hub.subscribe() as queue:
        await hub.start()
        for _ in range(100):
            if hub.available:
                break
            await asyncio.sleep(0.01)
        assert hub.available

        item = await asyncio.wait_for(queue.get(), timeout=2)
        if item == RESYNC:
            item = await asyncio.wait_for(queue.get(), timeout=2)
        assert item == CLOSE

        for _ in range(100):
            if not hub.available:
                break
            await asyncio.sleep(0.01)
        assert hub.available is False

        with contextlib.suppress(asyncio.CancelledError):
            await hub.stop()
