"""The ingestion worker process.

Runs the backend image with a different entrypoint, so it shares `Settings`, the ORM
models, the repositories, and the access resolver rather than growing a parallel copy
of any of them.

Three things run concurrently: the main ingest consumer, one consumer per retry
topic, and a sweep that recovers jobs Kafka never received.
"""

import asyncio
import logging
import uuid

from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.embedder import build_embedder, probe_dimensions
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import QdrantVectorStore, collection_name
from app.queue.consumer import IngestionConsumer
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.retry import RetryConsumer
from app.queue.topics import RETRY_TOPICS, IngestionMessage
from app.repositories.project import ProjectRepository
from app.repositories.refresh_token import RefreshTokenRepository

logger = logging.getLogger(__name__)

RECONCILE_INTERVAL_SECONDS = 60
STRANDED_AFTER_SECONDS = 120


async def reconcile_once(
    *, repository: ProjectRepository, producer: TopicProducer, topic: str
) -> int:
    """Re-enqueue every job that was lost. Returns how many.

    Covers two gaps the queue cannot close on its own: `POST /projects` committed the
    row but the produce failed, and a worker died holding a lease. Safe to run on
    every worker concurrently — the lease claim deduplicates, so a duplicate message
    costs one skipped poll.
    """
    stranded = await repository.find_stranded(pending_older_than_seconds=STRANDED_AFTER_SECONDS)
    for project in stranded:
        logger.info("re-enqueueing stranded project %s (status=%s)", project.id, project.status)
        await producer.produce_to(
            topic,
            IngestionMessage(
                project_id=project.id,
                # A fresh job id: reusing the old one could match `last_job_id` on
                # the row, and the claim would refuse the replacement message.
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=0,
                original_topic=topic,
            ),
        )
    return len(stranded)


async def reconcile_loop(*, producer: TopicProducer, topic: str) -> None:
    """The 60-second tick: recover lost jobs and prune dead refresh tokens.

    `docs/PRD.md` §5.1 schedules the `refresh_tokens` cleanup for "M1, with the job
    scheduler". This loop is that scheduler.
    """
    sessionmaker = get_sessionmaker()
    while True:
        await asyncio.sleep(RECONCILE_INTERVAL_SECONDS)
        try:
            async with sessionmaker() as session:
                await reconcile_once(
                    repository=ProjectRepository(session), producer=producer, topic=topic
                )
                pruned = await RefreshTokenRepository(session).delete_expired_and_revoked()
                await session.commit()
                if pruned:
                    logger.info("pruned %d dead refresh tokens", pruned)
        except Exception:
            logger.exception("reconcile tick failed")


async def main() -> None:
    """Start the consumers and the sweep, and run until cancelled."""
    logging.basicConfig(level=logging.INFO)
    settings = get_settings()
    worker_id = f"worker-{uuid.uuid4().hex[:8]}"

    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_ingest_partitions,
    )

    producer = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers, topic=settings.kafka_ingest_topic
    )
    await producer.start()

    # Probed once at startup: the width names the collection, so guessing it wrong
    # is not a small mistake.
    embedder = build_embedder(settings)
    embedder.dimensions = await probe_dimensions(embedder)
    collection = collection_name(
        provider=settings.embedding_provider,
        model=settings.embedding_model,
        dimensions=embedder.dimensions,
    )
    logger.info("worker %s using collection %s", worker_id, collection)

    def build_pipeline(session: AsyncSession) -> IngestionPipeline:
        """A pipeline bound to one job's session."""
        return IngestionPipeline(
            session,
            settings,
            embedder=embedder,
            store=QdrantVectorStore(
                url=settings.qdrant_url, collection=collection, dimensions=embedder.dimensions
            ),
            chunker=LanguageAwareChunker(
                chunk_size=settings.chunk_size, chunk_overlap=settings.chunk_overlap
            ),
        )

    consumer = IngestionConsumer(
        settings=settings,
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_pipeline=build_pipeline,
        worker_id=worker_id,
    )

    tasks = [
        asyncio.create_task(consumer.run()),
        asyncio.create_task(reconcile_loop(producer=producer, topic=settings.kafka_ingest_topic)),
        *[
            asyncio.create_task(
                RetryConsumer(settings=settings, producer=producer, topic=topic).run()
            )
            for topic, _ in RETRY_TOPICS
        ],
    ]

    try:
        await asyncio.gather(*tasks)
    finally:
        for task in tasks:
            task.cancel()
        await producer.stop()


if __name__ == "__main__":
    asyncio.run(main())
