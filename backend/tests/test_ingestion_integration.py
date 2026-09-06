"""End to end against systems the unit suite fakes.

Everything else in this suite fakes the queue and the vector store. This file exists
for properties that cannot be reproduced against a fake:

- that a job taking longer than `max.poll.interval.ms` does not get the member
  evicted, redelivered, and run a second time (needs a real broker), and
- that `QdrantVectorStore.scroll`'s client-side prefix narrowing still matters
  against Qdrant's real full-text tokenizer (needs real Qdrant) —
  `InMemoryVectorStore.scroll` collapses the server-side token filter and the
  client-side prefix check into a single `startswith`, so no unit test can tell
  whether the narrowing is load-bearing or dead code.

**On the poll interval.** aiokafka's default is five minutes, so a test that runs a
"long" job for fifteen seconds is not testing anything — it passes with the pause
removed. The consumer under test is therefore built with a deliberately tiny interval
(`SHORT_POLL_INTERVAL_MS`), which is the only way the failure this file exists to
catch can be made to happen inside a test's lifetime. That is also why this is the one
place a real broker is required: eviction and redelivery are the broker's behaviour,
not the client's, and a fake would just be asserting our own assumptions back at us.
"""

import asyncio
import subprocess
import uuid
from collections.abc import AsyncIterator
from pathlib import Path

import pytest
from aiokafka import AIOKafkaConsumer
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import Chunk, LanguageAwareChunker
from app.ingestion.cloner import CloneResult
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import InMemoryVectorStore, QdrantVectorStore
from app.models.project import ProjectStatus
from app.queue.consumer import IngestionConsumer
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.topics import CHECKLIST_TOPIC, INGEST_TOPIC, IngestionMessage
from app.repositories.project import ProjectRepository
from tests.factories import create_project

pytestmark = pytest.mark.integration

# Low enough that a job can outlast it inside a test, high enough that the group
# forms and heartbeats settle first. The production consumer keeps aiokafka's
# five-minute default; only this file shortens it.
SHORT_POLL_INTERVAL_MS = 6_000
# Comfortably past the interval above, so eviction is what we are waiting on rather
# than luck.
LONG_JOB_SECONDS = 14
INDEX_TIMEOUT_SECONDS = 60


class ShortIntervalConsumer(IngestionConsumer):
    """The shipped consumer with only the poll interval shortened.

    Subclassed rather than reconfigured so every other property under test — the
    pause, the keep-alive poll, the commit ordering, the rebalance listener — is the
    production one. The built consumer is kept so the test can read its group
    membership while a job is in flight.
    """

    consumer: AIOKafkaConsumer | None = None

    def _build_consumer(self, **overrides: object) -> AIOKafkaConsumer:
        self.consumer = super()._build_consumer(
            max_poll_interval_ms=SHORT_POLL_INTERVAL_MS, **overrides
        )
        return self.consumer

    def member_id(self) -> str:
        """This worker's seat in the consumer group.

        Kafka issues a new one on every join, so a changed id is proof the member was
        thrown out and rejoined — which is the eviction this test exists to rule out.
        Reaching into the coordinator is the only way to see it; aiokafka exposes no
        public accessor.
        """
        assert self.consumer is not None
        return str(self.consumer._coordinator.member_id)


@pytest.fixture
async def producer() -> AsyncIterator[KafkaIngestionQueue]:
    settings = get_settings()
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_ingest_partitions,
    )
    queue = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=INGEST_TOPIC,
        checklist_topic=CHECKLIST_TOPIC,
        mock_data_topic=settings.kafka_mock_data_topic,
    )
    await queue.start()
    yield queue
    await queue.stop()


def message_for(project_id: uuid.UUID) -> IngestionMessage:
    return IngestionMessage(
        project_id=project_id,
        job_id=uuid.uuid4(),
        attempt=0,
        not_before_ms=0,
        original_topic=INGEST_TOPIC,
    )


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

    async def fake_clone(validated: object, **kwargs: object) -> CloneResult:
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

    await producer.enqueue(message_for(project.id))

    task = asyncio.create_task(consumer.run())
    try:
        for _ in range(INDEX_TIMEOUT_SECONDS):
            await asyncio.sleep(1)
            await db_session.refresh(project)
            if project.status == ProjectStatus.READY.value:
                break
    finally:
        task.cancel()

    assert project.status == ProjectStatus.READY.value
    assert store.points, "the job reported ready without writing any vectors"
    assert project.last_job_id is not None


async def test_a_long_job_does_not_trigger_a_rebalance(
    db_session: AsyncSession, producer: KafkaIngestionQueue
) -> None:
    """The property the pause-and-keep-polling pattern exists for.

    aiokafka measures liveness as *fetcher idle time*: if `getmany` is not called
    within `max.poll.interval.ms`, the client leaves the group on its own. A worker
    that simply awaited a twenty-minute clone-and-embed would therefore be evicted
    mid-job, every time, and the partition would be handed to somebody else while the
    original was still working on it. The loop avoids that by continuing to poll
    throughout the job with every partition paused, so each poll is a live heartbeat
    that returns nothing.

    **Why membership, not the run count.** An eviction here does not produce a second
    run: the redelivered message is refused by the database lease, which is exactly
    what the lease is for. So counting runs cannot see this defect — verified by
    removing the keep-alive poll and watching `runs == 1` hold while the logs showed a
    LeaveGroup and a rejoin. The observable fact is the seat itself.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    started = asyncio.Event()
    runs = 0

    class SlowPipeline:
        async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
            nonlocal runs
            runs += 1
            started.set()
            await asyncio.sleep(LONG_JOB_SECONDS)

    consumer = ShortIntervalConsumer(
        settings=get_settings(),
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=lambda session: SlowPipeline(),
        worker_id="slow-worker",
    )

    await producer.enqueue(message_for(project.id))

    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.wait_for(started.wait(), timeout=30)
        seat_before = consumer.member_id()
        # Outlast the interval by a clear margin: the job is more than twice it.
        await asyncio.sleep(LONG_JOB_SECONDS + 2)
        seat_after = consumer.member_id()
    finally:
        task.cancel()

    assert seat_before, "the worker never joined the group"
    assert seat_after == seat_before, (
        "the worker was evicted mid-job and rejoined: the job outlasted "
        "max.poll.interval.ms without the keep-alive poll holding its seat"
    )
    assert runs == 1


async def test_a_redelivered_message_is_refused_by_the_lease(
    db_session: AsyncSession, producer: KafkaIngestionQueue
) -> None:
    """At-least-once delivery is the broker's promise, and the lease is what makes it
    survivable: a duplicate costs one skipped poll, not a second clone.

    This is the guarantee the loop leans on every time it absorbs an error and leaves
    the offset put, so it is worth pinning against a real broker rather than only
    against `handle_message`.
    """
    project = await create_project(db_session, status=ProjectStatus.PENDING)
    await db_session.commit()

    # A live lease held by somebody else — exactly what a duplicate delivery meets.
    await ProjectRepository(db_session).claim(
        project_id=project.id, job_id=uuid.uuid4(), worker_id="other-worker", lease_seconds=300
    )
    await db_session.commit()

    runs = 0

    class CountingPipeline:
        async def run(self, *, project_id: uuid.UUID, job_id: uuid.UUID, worker_id: str) -> None:
            nonlocal runs
            runs += 1

    consumer = IngestionConsumer(
        settings=get_settings(),
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=lambda session: CountingPipeline(),
        worker_id="integration-worker",
    )

    await producer.enqueue(message_for(project.id))

    task = asyncio.create_task(consumer.run())
    try:
        await asyncio.sleep(15)
    finally:
        task.cancel()

    assert runs == 0, "the lease did not stop a second worker from starting the job"


async def test_scroll_narrows_a_match_text_false_positive_against_real_qdrant() -> None:
    """`QdrantVectorStore.scroll` filters `file_path` with `MatchText`, which is a
    full-text match over word tokens, not a prefix match: `path_prefix="app/auth"`
    tokenizes to `{app, auth}`, and Qdrant's server-side filter alone also returns
    `vendor/app/auth/nested.py`, which shares both word tokens but is not a real
    prefix match. `scroll` narrows each page with a client-side `startswith` check
    after the server-side filter to correct for exactly this.

    `InMemoryVectorStore.scroll` cannot exercise this: its fake collapses the
    server-side token filter and the client-side prefix check into one `startswith`,
    so it can never diverge from a real prefix match and no unit test run against it
    can tell whether the client-side narrowing in `QdrantVectorStore.scroll` is still
    doing anything. This test is pinned against a real collection so that narrowing
    cannot later be deleted as apparently redundant.
    """
    settings = get_settings()
    # A name that cannot collide with a real collection: those are
    # `code_chunks__<provider>__<model>__<dimensions>` (`collection_name` in
    # `app/ingestion/vector_store.py`), never `scroll_probe_*`.
    collection = f"scroll_probe_{uuid.uuid4().hex}"
    store = QdrantVectorStore(url=settings.qdrant_url, collection=collection, dimensions=3)
    await store.ensure_collection()
    project_id = uuid.uuid4()

    def chunk(path: str) -> Chunk:
        return Chunk(
            file_path=path,
            start_line=1,
            end_line=2,
            language="python",
            symbol=None,
            chunk_index=0,
            text="def login(): ...",
        )

    try:
        await store.upsert(
            project_id=project_id,
            generation=1,
            chunks=[chunk("app/auth/login.py"), chunk("vendor/app/auth/nested.py")],
            vectors=[[0.1, 0.2, 0.3], [0.1, 0.2, 0.3]],
            commit_sha="a" * 40,
        )

        pages = [
            page
            async for page in store.scroll(
                project_id=project_id, generation=1, path_prefix="app/auth", page_size=10
            )
        ]

        payloads = [payload for page in pages for payload in page]
        assert [payload["file_path"] for payload in payloads] == ["app/auth/login.py"]
    finally:
        # Test seam, matching `tests/test_vector_store.py`'s convention of reaching
        # into the private client where the public surface has no delete-collection
        # call. Runs even if the assertion above fails.
        await store._client.delete_collection(collection)
