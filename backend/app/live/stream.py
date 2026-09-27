"""The body of `GET /events`.

Access is re-checked, not trusted: before forwarding a project-scoped event the stream
reloads the caller's grants (through the grant cache) and asks `access.live_event_visible_to`,
and on every heartbeat it re-reads the user row and the caller's own session, closing the
stream when the user is gone, must change their password, or that session (refresh-token
family) has been signed out or revoked elsewhere. The access token expiring mid-stream is
therefore harmless.

Each check opens its own session from the sessionmaker — never the request-scoped one, for
the reason `.claude/rules/rag.md` gives for the answer stream.

A re-check is bounded two ways so a burst of project-scoped events cannot turn into a burst
of database work: at most `_RECHECK_CONCURRENCY` re-checks run at once across every open
stream in this process, and a successful re-check is reused for `_RECHECK_REUSE_SECONDS` — an
event or heartbeat due within that window sees the same `current` without opening a session.
A re-check that raises is treated as "closed": the exception is logged and the stream ends
cleanly rather than propagating out of the generator, so one flaky check costs one client a
reconnect instead of taking the whole request down.

The heartbeat is scheduled on a clock of its own (`next_heartbeat_due`), not on "however long
since the last `queue.get()` returned" — a queue kept busy by events invisible to this caller
must not starve the `: ping` or the re-check it carries.
"""

import asyncio
import logging
import time
from collections.abc import AsyncGenerator
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import live_event_visible_to
from app.core.middleware import AuthenticatedUser, load_authenticated_user
from app.live.bus import LiveEventHub
from app.live.fanout import CLOSE, RESYNC, QueueItem
from app.repositories.refresh_token import RefreshTokenRepository
from app.schemas.conversation import encode_event
from app.schemas.live import InvalidateEvent, ReadyEvent, ResyncEvent

logger = logging.getLogger(__name__)

HEARTBEAT: Final = b": ping\n\n"

_RECHECK_CONCURRENCY: Final = 4
_RECHECK_REUSE_SECONDS: Final = 2.0

_recheck_semaphore = asyncio.Semaphore(_RECHECK_CONCURRENCY)


async def _recheck(
    sessionmaker: async_sessionmaker[AsyncSession], user: AuthenticatedUser
) -> AuthenticatedUser | None:
    """Reload the caller, or `None` if the stream must close.

    Never raises: a re-check failure (a database hiccup, anything unexpected) is logged
    at `WARNING` with the user id only and treated the same as "gone" — the stream closes
    and the client reconnects, rather than an exception propagating out of the generator
    and killing the request some other way.
    """
    try:
        async with _recheck_semaphore, sessionmaker() as session:
            fresh = await load_authenticated_user(session, user.id, user.session_id)
            if fresh is None or fresh.must_change_password:
                return None
            if user.session_id is not None:
                live = await RefreshTokenRepository(session).family_is_live(user.session_id)
                if not live:
                    return None
            return fresh
    except Exception:
        logger.warning("live event re-check failed for user_id=%s", user.id, exc_info=True)
        return None


async def _recheck_or_reuse(
    sessionmaker: async_sessionmaker[AsyncSession],
    current: AuthenticatedUser,
    last_checked_at: float | None,
) -> tuple[AuthenticatedUser | None, float | None]:
    """`_recheck`, unless the last successful one is still within its reuse window.

    Returns the (possibly reused) user and the timestamp to remember for next time. The
    timestamp only advances on a successful check — a reused result does not extend its
    own window, and a failed check leaves the previous successful timestamp in place so
    a single hiccup does not silence every re-check for the next two seconds too.
    """
    now = time.monotonic()
    if last_checked_at is not None and now - last_checked_at < _RECHECK_REUSE_SECONDS:
        return current, last_checked_at
    refreshed = await _recheck(sessionmaker, current)
    if refreshed is None:
        return None, last_checked_at
    return refreshed, now


async def live_event_stream(
    *,
    user: AuthenticatedUser,
    hub: LiveEventHub,
    sessionmaker: async_sessionmaker[AsyncSession],
    heartbeat_seconds: float,
    max_seconds: float,
) -> AsyncGenerator[bytes]:
    """Yield SSE frames until the client leaves, a re-check fails, or the cap."""
    deadline = time.monotonic() + max_seconds
    current = user
    last_checked_at: float | None = None
    async with hub.subscribe() as queue:
        yield encode_event(ReadyEvent())
        next_heartbeat_due = time.monotonic() + heartbeat_seconds
        while True:
            now = time.monotonic()
            if now >= deadline:
                return
            timeout = min(deadline - now, max(next_heartbeat_due - now, 0.0))
            item: QueueItem | None
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                item = None

            if time.monotonic() >= next_heartbeat_due:
                refreshed, last_checked_at = await _recheck_or_reuse(
                    sessionmaker, current, last_checked_at
                )
                if refreshed is None:
                    return
                current = refreshed
                next_heartbeat_due = time.monotonic() + heartbeat_seconds
                if deadline - time.monotonic() > 0:
                    yield HEARTBEAT

            if item is None:
                continue
            if item == RESYNC:
                yield encode_event(ResyncEvent())
                continue
            if item == CLOSE:
                return
            if item.kind != "notification":
                refreshed, last_checked_at = await _recheck_or_reuse(
                    sessionmaker, current, last_checked_at
                )
                if refreshed is None:
                    return
                current = refreshed
            if live_event_visible_to(current, item):
                yield encode_event(
                    InvalidateEvent(kind=item.kind, id=item.id, project_id=item.project_id)
                )
