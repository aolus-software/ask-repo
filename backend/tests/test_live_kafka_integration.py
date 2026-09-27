"""A real Kafka round trip: publish on one side, a subscribed hub receives it."""

import asyncio
import uuid

import pytest

from app.config import get_settings
from app.live.events import project_event
from app.live.kafka import LIVE_TOPIC_CONFIGS, KafkaLiveEventHub, KafkaLivePublisher
from app.queue.producer import ensure_topics

pytestmark = pytest.mark.integration


async def test_a_published_event_reaches_a_subscriber() -> None:
    settings = get_settings()
    topic = f"askrepo.live.test.{uuid.uuid4().hex[:8]}"
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=1,
        topics=(topic,),
        topic_configs=LIVE_TOPIC_CONFIGS,
    )
    hub = KafkaLiveEventHub(bootstrap_servers=settings.kafka_bootstrap_servers, topic=topic)
    publisher = KafkaLivePublisher(bootstrap_servers=settings.kafka_bootstrap_servers, topic=topic)
    await hub.start()
    await publisher.start()
    try:
        for _ in range(100):
            if hub.available:
                break
            await asyncio.sleep(0.1)
        assert hub.available
        event = project_event(uuid.uuid4())
        async with hub.subscribe() as queue:
            publisher.submit([event])
            assert await asyncio.wait_for(queue.get(), timeout=10) == event
    finally:
        await publisher.stop()
        await hub.stop()
