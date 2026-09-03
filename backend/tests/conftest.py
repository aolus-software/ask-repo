"""Shared fixtures.

Tests run against real Postgres and real Redis (D8): `timestamptz`, the partial
unique index on `email`, and asyncpg itself all behave differently on SQLite, and a
suite that passes on SQLite while production breaks is worse than no suite.

`make infra` must be running. See CONTRIBUTING.md.
"""

import asyncio
import subprocess
import uuid
from collections.abc import AsyncIterator, Callable, Iterator
from pathlib import Path

import asyncpg
import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.security import create_access_token, hash_password
from app.db.session import get_sessionmaker, reset_engine
from app.ingestion.embedder import FakeEmbedder
from app.ingestion.vector_store import InMemoryVectorStore
from app.models import Base, User
from app.queue.protocol import InMemoryIngestionQueue
from app.rag.answerer import Answerer
from app.rag.graph.state import Classification, EvidenceVerdict
from app.rag.retriever import CodeRetriever
from tests.fakes import ScriptedChatModel

BACKEND_ROOT = Path(__file__).resolve().parent.parent
TEST_DB_NAME = "askrepo_test"
TEST_REDIS_DB = 15


def _swap_database(url: str, name: str) -> str:
    """Replace the database name in a connection URL, keeping credentials and host."""
    base, _, _ = url.rpartition("/")
    return f"{base}/{name}"


@pytest.fixture(scope="session", autouse=True)
def _test_environment() -> Iterator[None]:
    """Point settings at the test database and Redis DB before anything reads them.

    Environment rather than a dependency override, because the auth middleware calls
    `get_settings()` directly rather than through `Depends` (see app/db/session.py).
    """
    dev = get_settings()
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("APP_ENV", "test")
        patch.setenv("DATABASE_URL", _swap_database(dev.database_url, TEST_DB_NAME))
        patch.setenv("REDIS_URL", _swap_database(dev.redis_url, str(TEST_REDIS_DB)))
        patch.setenv("SECRET_KEY", "test-secret-key-not-used-anywhere-real")
        patch.setenv("BCRYPT_COST", "4")  # keep the suite fast; cost is not under test
        patch.setenv("PAT_ENCRYPTION_KEY", "Hu25IBLmyXgJmARywo5aj5DQrr3yGs3RPgqyC7_kVDo=")
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


@pytest.fixture(scope="session", autouse=True)
async def _migrated_database(_test_environment: None) -> AsyncIterator[None]:
    """Create `askrepo_test` if absent and bring it to head.

    Runs the real migrations, never `create_all`: the migrations are part of what is
    under test, and the partial index must be exercised exactly as shipped.
    """
    settings = get_settings()
    admin_url = _swap_database(settings.database_url, "postgres").replace(
        "postgresql+asyncpg://", "postgresql://"
    )
    connection = await asyncpg.connect(admin_url)
    try:
        exists = await connection.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", TEST_DB_NAME
        )
        if not exists:
            await connection.execute(f'CREATE DATABASE "{TEST_DB_NAME}"')
    finally:
        await connection.close()

    subprocess.run(["uv", "run", "alembic", "upgrade", "head"], cwd=BACKEND_ROOT, check=True)
    yield
    await reset_engine()


@pytest.fixture(autouse=True)
async def _clean_tables(_migrated_database: None) -> AsyncIterator[None]:
    """Empty every table between tests.

    TRUNCATE rather than a rolled-back outer transaction: services commit, and the
    savepoint-restart recipe needed to survive a commit is fragile enough to produce
    failures that look like product bugs.
    """
    tables = ", ".join(f'"{table.name}"' for table in reversed(Base.metadata.sorted_tables))
    async with get_sessionmaker()() as session:
        await session.execute(text(f"TRUNCATE {tables} RESTART IDENTITY CASCADE"))
        await session.commit()
    yield


@pytest.fixture(autouse=True)
async def _clean_redis(_test_environment: None) -> AsyncIterator[None]:
    """Flush the test Redis DB between tests.

    Login rate limiting uses fixed 60-second windows keyed by IP, and every test
    client shares the same address, so a limiter test that spends the per-IP budget
    would otherwise bleed 429s into every test that runs afterward in the same window.
    """
    client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield
    await client.aclose()


@pytest.fixture
async def db_session() -> AsyncIterator[AsyncSession]:
    """A session for tests that talk to repositories directly."""
    async with get_sessionmaker()() as session:
        yield session


@pytest.fixture
def sessionmaker() -> async_sessionmaker[AsyncSession]:
    """The real sessionmaker, for a stream under test to open its own session from --
    exactly as `stream_turn`/`stream_checklist_turn` do outside a request."""
    return get_sessionmaker()


@pytest.fixture
async def redis_client() -> AsyncIterator[aioredis.Redis]:
    """Redis on the test DB index, flushed before use."""
    client = aioredis.from_url(get_settings().redis_url, decode_responses=True)
    await client.flushdb()
    yield client
    await client.aclose()


@pytest.fixture
def app() -> FastAPI:
    """A freshly built app, so middleware and overrides don't leak between tests."""
    from app.main import create_app

    return create_app()


@pytest.fixture
async def client(app: FastAPI) -> AsyncIterator[AsyncClient]:
    """Async HTTP client. `AsyncClient` rather than `TestClient` so route tests share
    the event loop with the database fixtures."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as async_client:
        yield async_client


@pytest.fixture
def ingestion_queue() -> InMemoryIngestionQueue:
    """The queue every route test enqueues into. Assert against `.messages`."""
    return InMemoryIngestionQueue()


@pytest.fixture
def vector_store() -> InMemoryVectorStore:
    """The store every conversation test retrieves from. Seed it, then ask."""
    return InMemoryVectorStore(dimensions=8)


@pytest.fixture
def chat_model() -> ScriptedChatModel:
    """The answering model every conversation test streams from.

    Its answer cites `[1]` and names only a retrieved path on purpose: an uncited or
    unrecognised-path answer would trip a grounding warning in every route test and
    bury the real ones. `structured_results` scripts the graph's two utility calls --
    classify, then grade -- so a route test exercises the real path without a
    provider.
    """
    return ScriptedChatModel(
        tokens=["Validation lives in ", "[1]", " app/core/repo_url.py."],
        invoke_result="How is the repository URL validated?",
        structured_results=[
            Classification(
                intent="codebase_question", search_query="How is the repository URL validated?"
            ),
            EvidenceVerdict(sufficient=True),
        ],
    )


def _fake_answerer_factory(
    store: InMemoryVectorStore, chat_model: ScriptedChatModel
) -> Callable[[str], Answerer]:
    """Ignores the collection name — the in-memory store is the only one there is.

    No `min_score`: `FakeEmbedder` derives its vectors from text length and carries
    no semantic meaning, so a relevance floor over them would admit or reject chunks
    at random. The floor is exercised in `tests/test_retriever.py` with an embedder
    built for it.
    """

    def answerer_for(collection: str) -> Answerer:
        return Answerer(
            retriever=CodeRetriever(
                store=store, embedder=FakeEmbedder(dimensions=8), top_k=12, max_chars=24_000
            ),
            chat_model=chat_model,
            model_id="test-model",
            semaphore=asyncio.Semaphore(2),
            settings=Settings(),
        )

    return answerer_for


@pytest.fixture
def app_with_queue(
    ingestion_queue: InMemoryIngestionQueue,
    vector_store: InMemoryVectorStore,
    chat_model: ScriptedChatModel,
) -> FastAPI:
    """The app with every out-of-process dependency replaced — broker, vector store,
    embedder, and chat model — so route tests need no Kafka, no Qdrant, no Ollama.

    The name is understated for historical reasons: it replaced only the broker when
    M1 shipped it.
    """
    from app.api.routes.checklist_modules import (
        get_checklist_queue,
        get_proposing_answerer_factory,
    )
    from app.api.routes.conversations import get_answerer_factory
    from app.api.routes.projects import get_ingestion_queue, get_store_factory
    from app.main import create_app

    application = create_app()
    application.dependency_overrides[get_ingestion_queue] = lambda: ingestion_queue
    application.dependency_overrides[get_answerer_factory] = lambda: _fake_answerer_factory(
        vector_store, chat_model
    )
    # The delete path is the only route that reaches the vector store. Without this
    # override, deleting an indexed project opens a real Qdrant connection and fails
    # with 503 against a collection the fake never created.
    application.dependency_overrides[get_store_factory] = lambda: lambda collection: vector_store
    # The checklist routes have their own queue and answerer dependencies, so
    # overriding the conversation ones does not cover them.
    application.dependency_overrides[get_checklist_queue] = lambda: ingestion_queue
    application.dependency_overrides[get_proposing_answerer_factory] = lambda: (
        _fake_answerer_factory(vector_store, chat_model)
    )
    return application


async def _authenticated_client(
    app_with_queue: FastAPI, db_session: AsyncSession, *, is_admin: bool
) -> AsyncIterator[AsyncClient]:
    """An `AsyncClient` authenticated as a freshly created, ready-to-use user.

    `must_change_password=False`, or the forced-password-change gate returns
    `403 PASSWORD_CHANGE_REQUIRED` on every `/projects` call. Every call creates a
    distinct account, so fixtures built on this represent genuinely different users.
    """
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash=hash_password("a-perfectly-fine-passphrase", cost=4),
        is_admin=is_admin,
        must_change_password=False,
    )
    db_session.add(user)
    await db_session.commit()

    settings = get_settings()
    token, _ = create_access_token(
        user.id, secret=settings.secret_key, ttl_minutes=settings.access_token_ttl_minutes
    )
    headers = {"Authorization": f"Bearer {token}"}

    transport = ASGITransport(app=app_with_queue)
    async with AsyncClient(
        transport=transport, base_url="http://test", headers=headers
    ) as async_client:
        yield async_client


@pytest.fixture
async def authed_client(
    app_with_queue: FastAPI, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """An `AsyncClient` authenticated as a freshly created, ready-to-use user."""
    async for async_client in _authenticated_client(app_with_queue, db_session, is_admin=False):
        yield async_client


@pytest.fixture
async def client_for_user_a(
    app_with_queue: FastAPI, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """A distinct authenticated user — the project creator in sharing/gating tests."""
    async for async_client in _authenticated_client(app_with_queue, db_session, is_admin=False):
        yield async_client


@pytest.fixture
async def client_for_user_b(
    app_with_queue: FastAPI, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """A second, distinct authenticated user — the reader/attacker in those tests."""
    async for async_client in _authenticated_client(app_with_queue, db_session, is_admin=False):
        yield async_client


@pytest.fixture
async def client_for_admin(
    app_with_queue: FastAPI, db_session: AsyncSession
) -> AsyncIterator[AsyncClient]:
    """A distinct authenticated admin, who overrides the destructive gate."""
    async for async_client in _authenticated_client(app_with_queue, db_session, is_admin=True):
        yield async_client
