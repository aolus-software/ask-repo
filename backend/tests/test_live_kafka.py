"""The Kafka hub's decoding and fan-out, without a broker."""

import uuid

from app.live.events import project_event
from app.live.kafka import DisabledLiveEventHub, KafkaLiveEventHub


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
