"""The Kafka hub's decoding and fan-out, without a broker."""

import logging
import uuid

import pytest

from app.live.events import project_event
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
