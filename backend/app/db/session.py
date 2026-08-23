"""Async engine, sessionmaker, and the request-scoped session dependency.

The engine is built lazily rather than at import time, and that is load-bearing:
`AuthContextMiddleware` builds its own session from the sessionmaker instead of
through `Depends`, so a test that only overrode the `get_session` dependency would
leave the middleware talking to the development database. Lazy construction means a
settings override reaches both paths (§11).
"""

from collections.abc import AsyncIterator

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from app.config import get_settings

_engine: AsyncEngine | None = None
_sessionmaker: async_sessionmaker[AsyncSession] | None = None


def get_engine() -> AsyncEngine:
    """The process-wide engine, created on first use."""
    global _engine
    if _engine is None:
        settings = get_settings()
        _engine = create_async_engine(settings.database_url, pool_pre_ping=True)
    return _engine


def get_sessionmaker() -> async_sessionmaker[AsyncSession]:
    """Session factory. Used by `get_session` and, directly, by the auth middleware."""
    global _sessionmaker
    if _sessionmaker is None:
        _sessionmaker = async_sessionmaker(get_engine(), expire_on_commit=False)
    return _sessionmaker


async def reset_engine() -> None:
    """Dispose the engine and clear the cached factory. Test hook only."""
    global _engine, _sessionmaker
    if _engine is not None:
        await _engine.dispose()
    _engine = None
    _sessionmaker = None


async def get_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency yielding one session per request. Services own commits."""
    async with get_sessionmaker()() as session:
        yield session
