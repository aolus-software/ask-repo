"""FastAPI application factory."""

import asyncio
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import (
    auth,
    checklist_change_sets,
    checklist_items,
    checklist_modules,
    conversations,
    health,
    index,
    mock_data_change_sets,
    mock_data_datasets,
    mock_data_records,
    projects,
    users,
)
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.logging import configure_logging
from app.core.middleware import AuthContextMiddleware
from app.ingestion.embedder import build_embedder
from app.queue.producer import KafkaIngestionQueue, ensure_topics
from app.queue.topics import ALL_CHECKLIST_TOPICS, ALL_MOCK_DATA_TOPICS
from app.rag.capability import probe_structured_output
from app.rag.chat import build_chat_model

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the process-wide dependencies: the Kafka producer, and M2's RAG objects.

    They land on `app.state` rather than in module globals, because that is where the
    route dependencies read them (`get_ingestion_queue`, `get_embedder`,
    `get_chat_model`, `get_answer_semaphore`) and it is what lets tests override them
    without opening a socket.

    The `APP_ENV=test` guard is deliberately the first thing that could touch a
    socket. The suite builds the real app and there is no broker in the test
    environment: an unguarded start blocks on the bootstrap address rather than
    failing, so the suite would hang rather than report. The RAG objects are built
    above it because constructing them opens no connection — `build_embedder` and
    `build_chat_model` only configure a client — and the suite needs them present.
    """
    settings = get_settings()

    # Built before the test guard below: constructing these opens no socket, and the
    # suite builds the real app, so the conversation dependencies must find them on
    # app.state even when the broker is skipped.
    app.state.embedder = build_embedder(settings)
    app.state.chat_model = build_chat_model(settings)
    # One permit pool for the whole process. Ollama serialises inference internally,
    # so uncapped concurrency makes every answer slower rather than the queue shorter
    # (`docs/PRD.md` §9).
    app.state.answer_semaphore = asyncio.Semaphore(settings.chat_max_concurrency)

    if settings.app_env == "test":
        logger.debug("APP_ENV=test: skipping the Kafka producer")
        yield
        return

    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_ingest_partitions,
    )
    # Broker auto-creation is off, and POST /checklist-modules/{id}/generate publishes
    # from this process -- an unensured topic would make every generate request fail
    # at produce time.
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_checklist_partitions,
        topics=ALL_CHECKLIST_TOPICS,
    )
    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_mock_data_partitions,
        topics=ALL_MOCK_DATA_TOPICS,
    )
    # A live call, deliberately after the test guard above: an instance should fail
    # to boot on a model it cannot use, not fail on the first generation
    # (`docs/PRD.md` §6).
    await probe_structured_output(app.state.chat_model)
    queue = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        topic=settings.kafka_ingest_topic,
        checklist_topic=settings.kafka_checklist_topic,
        mock_data_topic=settings.kafka_mock_data_topic,
    )
    await queue.start()
    app.state.ingestion_queue = queue
    try:
        yield
    finally:
        await queue.stop()


def create_app() -> FastAPI:
    settings = get_settings()

    # Uvicorn configures its own loggers and leaves the root logger at WARNING, so
    # without this every `logger.info` in the API process is discarded -- including
    # the routing and grading lines that are the *only* record of how a turn was
    # answered, since the graph deliberately stores no trace
    # (`docs/superpowers/specs/2026-08-30-m3-langgraph-design.md` §2.4). It also
    # reclaims uvicorn's own handlers, which are otherwise the only lines in the
    # process with no timestamp -- see `app/core/logging.py`.
    configure_logging("api")

    app = FastAPI(
        title=settings.app_name,
        version=settings.app_version,
        description="Codebase-aware assistant API.",
        debug=settings.debug,
        lifespan=lifespan,
    )

    register_exception_handlers(app)

    # Registered BEFORE CORS on purpose. add_middleware inserts at index 0 and the
    # stack is applied reversed, so the last-added middleware is outermost — CORS
    # must be outside this one, or the gate's 403 reaches the browser without CORS
    # headers and the frontend sees an opaque network error.
    app.add_middleware(AuthContextMiddleware)

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    app.include_router(index.router)
    app.include_router(health.router)
    app.include_router(auth.router)
    app.include_router(users.router)
    app.include_router(projects.router)
    app.include_router(conversations.router)
    app.include_router(checklist_modules.router)
    app.include_router(checklist_items.router)
    app.include_router(checklist_change_sets.router)
    app.include_router(mock_data_datasets.router)
    app.include_router(mock_data_records.router)
    app.include_router(mock_data_change_sets.router)

    return app


app = create_app()
