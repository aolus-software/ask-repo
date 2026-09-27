"""The body of `GET /events`.

Access is re-checked, not trusted: before forwarding a project-scoped event the stream
reloads the caller's grants (through the grant cache) and asks `access.live_event_visible_to`,
and on every heartbeat it re-reads the user row, closing the stream when the user is gone or
must change their password. The access token expiring mid-stream is therefore harmless.

Each check opens its own session from the sessionmaker — never the request-scoped one, for
the reason `.claude/rules/rag.md` gives for the answer stream.
"""

import asyncio
import time
from collections.abc import AsyncGenerator
from typing import Final

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.access import live_event_visible_to
from app.core.middleware import AuthenticatedUser, load_authenticated_user
from app.live.bus import LiveEventHub
from app.live.fanout import RESYNC
from app.schemas.conversation import encode_event
from app.schemas.live import InvalidateEvent, ReadyEvent, ResyncEvent

HEARTBEAT: Final = b": ping\n\n"


async def _recheck(
    sessionmaker: async_sessionmaker[AsyncSession], user: AuthenticatedUser
) -> AuthenticatedUser | None:
    async with sessionmaker() as session:
        fresh = await load_authenticated_user(session, user.id, user.session_id)
    if fresh is None or fresh.must_change_password:
        return None
    return fresh


async def live_event_stream(
    *,
    user: AuthenticatedUser,
    hub: LiveEventHub,
    sessionmaker: async_sessionmaker[AsyncSession],
    heartbeat_seconds: float,
    max_seconds: float,
) -> AsyncGenerator[bytes]:
    """Yield SSE frames until the client leaves, the user fails a re-check, or the cap."""
    deadline = time.monotonic() + max_seconds
    current = user
    async with hub.subscribe() as queue:
        yield encode_event(ReadyEvent())
        while (remaining := deadline - time.monotonic()) > 0:
            timeout = min(heartbeat_seconds, remaining)
            try:
                item = await asyncio.wait_for(queue.get(), timeout=timeout)
            except TimeoutError:
                refreshed = await _recheck(sessionmaker, current)
                if refreshed is None:
                    return
                current = refreshed
                if deadline - time.monotonic() > 0:
                    yield HEARTBEAT
                continue
            if item == RESYNC:
                yield encode_event(ResyncEvent())
                continue
            if item.kind != "notification":
                refreshed = await _recheck(sessionmaker, current)
                if refreshed is None:
                    return
                current = refreshed
            if live_event_visible_to(current, item):
                yield encode_event(
                    InvalidateEvent(kind=item.kind, id=item.id, project_id=item.project_id)
                )
