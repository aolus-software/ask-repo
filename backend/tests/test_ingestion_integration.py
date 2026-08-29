"""End to end against a real broker.

Everything else in this suite fakes the queue. This file exists for the one property
that cannot be faked: that a job taking longer than `max.poll.interval.ms` does not
trigger a rebalance and get run twice.
"""

import asyncio
import subprocess
import uuid
from pathlib import Path

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.cloner import CloneResult
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import InMemoryVectorStore
from app.models.project import ProjectStatus
from app.queue.consumer import IngestionConsumer
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.topics import INGEST_TOPIC, IngestionMessage
from tests.factories import create_project

pytestmark = pytest.mark.integration


@pytest.fixture
async def producer() -> KafkaIngestionQueue:
    settings = get_settings()
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers, partitions=settings.kafka_ingest_partitions
    )
    queue = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers, topic=INGEST_TOPIC
    )
    await queue.start()
    yield queue
    await queue.stop()


async def test_a_produced_job_is_consumed_and_indexed(
    db_session: AsyncSession, producer: KafkaIngestionQueue, tmp_path: Path
) -> None:
    """The whole loop: produce → consume → claim → index → ready."""
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "main.py").write_text("def main() -> None:\n    pass\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    store = InMemoryVectorStore(dimensions=4)

    async def fake_clone(validated, **kwargs) -> CloneResult:  # noqa: ANN001, ANN003 - test stub
        return CloneResult(path=repo, commit_sha="a" * 40)

    def build_pipeline(session: AsyncSession) -> IngestionPipeline:
        return IngestionPipeline(
            session,
            get_settings(),
            embedder=FakeEmbedder(dimensions=4),
            store=store,
            chunker=LanguageAwareChunker(chunk_size=1200, chunk_overlap=150),
            clone_fn=fake_clone,
        )

    consumer = IngestionConsumer(
        settings=get_settings(),
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=build_pipeline,
        worker_id="integration-worker",
    )

    await producer.enqueue(
        IngestionMessage(
            project_id=project.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic=INGEST_TOPIC,
        )
    )

    task = asyncio.create_task(consumer.run())
    try:
        for _ in range(60):
            await asyncio.sleep(1)
            await db_session.refresh(project)
            if project.status == ProjectStatus.READY:
                break
    finally:
        task.cancel()

    assert project.status == ProjectStatus.READY
    assert store.points


async def test_a_long_job_does_not_trigger_a_rebalance(
    db_session: AsyncSession, producer: KafkaIngestionQueue, tmp_path: Path
) -> None:
    """The property the pause pattern exists for.

    A job that outlasts the poll interval must run exactly once. Without pausing,
    the broker evicts the member mid-job and a second consumer starts the same work.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    runs = 0

    class SlowPipeline:
        async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
            nonlocal runs
            runs += 1
            # Comfortably past the default 5s poll timeout used in this test setup.
            await asyncio.sleep(15)

    consumer = IngestionConsumer(
        settings=get_settings(),
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=lambda session: SlowPipeline(),
        worker_id="slow-worker",
    )

    await producer.enqueue(
        IngestionMessage(
            project_id=project.id,
            job_id=uuid.uuid4(),
            attempt=0,
            not_before_ms=0,
            original_topic=INGEST_TOPIC,
        )
    )

    task = asyncio.create_task(consumer.run())
    await asyncio.sleep(25)
    task.cancel()

    assert runs == 1
