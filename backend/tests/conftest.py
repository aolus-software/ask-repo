"""Shared fixtures.

Tests run against real Postgres and real Redis (D8): `timestamptz`, the partial
unique index on `email`, and asyncpg itself all behave differently on SQLite, and a
suite that passes on SQLite while production breaks is worse than no suite.

`make infra` must be running. See CONTRIBUTING.md.
"""

import subprocess
from collections.abc import AsyncIterator, Iterator
from pathlib import Path

import asyncpg
import pytest
import redis.asyncio as aioredis
from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import get_settings
from app.db.session import get_sessionmaker, reset_engine
from app.models import Base

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
