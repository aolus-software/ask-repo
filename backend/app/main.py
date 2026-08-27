"""FastAPI application factory."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from app.api.routes import auth, health, index, projects, users
from app.config import get_settings
from app.core.errors import register_exception_handlers
from app.core.middleware import AuthContextMiddleware
from app.queue.producer import KafkaIngestionQueue, ensure_topics

logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    """Own the Kafka producer's lifetime.

    The queue lands on `app.state.ingestion_queue` rather than in a module global,
    because that is where `get_ingestion_queue` (app/api/routes/projects.py) reads it
    and it is what lets tests override the dependency without opening a socket.

    The `APP_ENV=test` guard is deliberately the first thing here, ahead of anything
    that could touch a socket. The suite builds the real app and there is no broker
    in the test environment: an unguarded start blocks on the bootstrap address
    rather than failing, so the suite would hang rather than report.
    """
    settings = get_settings()
    if settings.app_env == "test":
        logger.debug("APP_ENV=test: skipping the Kafka producer")
        yield
        return

    await ensure_topics(
        bootstrap_servers=settings.kafka_bootstrap_servers,
        partitions=settings.kafka_ingest_partitions,
    )
    queue = KafkaIngestionQueue(
        bootstrap_servers=settings.kafka_bootstrap_servers, topic=settings.kafka_ingest_topic
    )
    await queue.start()
    app.state.ingestion_queue = queue
    try:
        yield
    finally:
        await queue.stop()


def create_app() -> FastAPI:
    settings = get_settings()

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

    return app


app = create_app()
