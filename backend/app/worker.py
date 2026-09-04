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

from app.checklist.generator import ChecklistGenerator
from app.config import get_settings
from app.db.session import get_sessionmaker
from app.ingestion.chunker import LanguageAwareChunker
from app.ingestion.embedder import build_embedder, probe_dimensions
from app.ingestion.pipeline import IngestionPipeline
from app.ingestion.vector_store import QdrantVectorStore, build_store_factory, collection_name
from app.queue.checklist import ChecklistConsumer
from app.queue.consumer import IngestionConsumer
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.protocol import TopicProducer
from app.queue.retry import RetryConsumer
from app.queue.topics import (
    ALL_CHECKLIST_TOPICS,
    CHECKLIST_RETRY_TOPICS,
    RETRY_TOPICS,
    ChecklistJobMessage,
    IngestionMessage,
)
from app.rag.chat import build_chat_model
from app.repositories.checklist_module import ChecklistModuleRepository
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


async def reconcile_modules_once(
    *, repository: ChecklistModuleRepository, producer: TopicProducer, topic: str
) -> int:
    """Re-enqueue every generation that was lost. Returns how many.

    Covers the same two gaps as `reconcile_once` does for projects: the route committed
    the row but the produce failed, and a worker died holding a lease.

    `claim_stranded` **takes** the rows rather than merely finding them, and that is
    what makes this safe to run repeatedly and on every worker at once. The claim
    cannot deduplicate here the way it does for ingestion: the message below carries a
    deliberately fresh `job_id`, so it is guaranteed claimable and a duplicate costs a
    whole generation instead of one skipped poll. Selecting without stamping publishes
    the same module on every tick for as long as it sits in `generating` with nobody on
    it -- one full generation per minute, indefinitely.
    """
    stranded = await repository.claim_stranded(generating_older_than_seconds=STRANDED_AFTER_SECONDS)
    for module_id in stranded:
        logger.info("re-enqueueing stranded checklist module %s", module_id)
        await producer.produce_to(
            topic,
            ChecklistJobMessage(
                module_id=module_id,
                # A fresh job id: reusing the old one could match `last_job_id` and
                # the claim would refuse the replacement message.
                job_id=uuid.uuid4(),
                attempt=0,
                not_before_ms=0,
                original_topic=topic,
            ),
        )
    return len(stranded)


async def reconcile_loop(*, producer: TopicProducer, topic: str, checklist_topic: str) -> None:
    """The 60-second tick: recover lost jobs of both kinds and prune dead refresh
    tokens.

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
                await reconcile_modules_once(
                    repository=ChecklistModuleRepository(session),
                    producer=producer,
                    topic=checklist_topic,
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
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_checklist_partitions,
        topics=ALL_CHECKLIST_TOPICS,
    )

    producer = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.kafka_ingest_topic,
        checklist_topic=settings.kafka_checklist_topic,
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

    # The worker answers with a chat model now, not only an embedder: generation maps
    # and reduces through one. Constructed here rather than per job -- building it
    # opens no connection, and one per message would rebuild a client per generation.
    chat_model = build_chat_model(settings)
    store_factory = build_store_factory(settings)

    def build_generator(session: AsyncSession) -> ChecklistGenerator:
        """A generator bound to one job's session."""
        return ChecklistGenerator(
            session, settings, store_factory=store_factory, chat_model=chat_model
        )

    checklist_consumer = ChecklistConsumer(
        settings=settings,
        sessionmaker=get_sessionmaker(),
        producer=producer,
        build_generator=build_generator,
        worker_id=worker_id,
    )

    tasks = [
        asyncio.create_task(consumer.run()),
        asyncio.create_task(checklist_consumer.run()),
        asyncio.create_task(
            reconcile_loop(
                producer=producer,
                topic=settings.kafka_ingest_topic,
                checklist_topic=settings.kafka_checklist_topic,
            )
        ),
        *[
            asyncio.create_task(
                RetryConsumer(
                    settings=settings,
                    producer=producer,
                    topic=topic,
                    decode=IngestionMessage.from_bytes,
                    destination_topic=settings.kafka_ingest_topic,
                ).run()
            )
            for topic, _ in RETRY_TOPICS
        ],
        *[
            asyncio.create_task(
                RetryConsumer(
                    settings=settings,
                    producer=producer,
                    topic=topic,
                    decode=ChecklistJobMessage.from_bytes,
                    destination_topic=settings.kafka_checklist_topic,
                ).run()
            )
            for topic, _ in CHECKLIST_RETRY_TOPICS
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
