"""The `/events` generator: ready first, access re-checked per event, closed on deactivation."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime

from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.core.grant_cache import get_grant_cache
from app.core.middleware import load_authenticated_user
from app.live.bus import InMemoryLiveEventBus
from app.live.events import notification_event, project_event
from app.live.stream import HEARTBEAT, live_event_stream
from app.models import User
from app.models.membership import ProjectMembership
from tests.conftest import GrantMembership
from tests.factories import create_project


async def _next(stream: AsyncIterator[bytes]) -> bytes:
    return await asyncio.wait_for(anext(stream), timeout=2)


async def _open(
    user: User,
    bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
    *,
    heartbeat: float = 5,
    max_seconds: float = 30,
) -> AsyncGenerator[bytes]:
    async with sessionmaker() as session:
        actor = await load_authenticated_user(session, user.id, None)
    assert actor is not None
    return live_event_stream(
        user=actor,
        hub=bus,
        sessionmaker=sessionmaker,
        heartbeat_seconds=heartbeat,
        max_seconds=max_seconds,
    )


async def test_ready_comes_first(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    stream = await _open(authed_user, live_bus, sessionmaker)
    assert (await _next(stream)).startswith(b"event: ready\n")
    await stream.aclose()


async def test_a_member_receives_their_projects_events_and_not_others(
    authed_user: User,
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    mine = await create_project(db_session, grant_owner=False)
    theirs = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await grant_membership(authed_user.id, mine.id, "viewer")
    stream = await _open(authed_user, live_bus, sessionmaker)
    await _next(stream)  # ready

    live_bus.submit([project_event(theirs.id), project_event(mine.id)])

    frame = await _next(stream)
    assert frame.startswith(b"event: invalidate\n")
    assert str(mine.id).encode() in frame
    assert str(theirs.id).encode() not in frame
    await stream.aclose()


async def test_an_admin_receives_every_projects_events(
    admin_user: User,
    db_session: AsyncSession,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    stream = await _open(admin_user, live_bus, sessionmaker)
    await _next(stream)

    live_bus.submit([project_event(project.id)])

    assert str(project.id).encode() in await _next(stream)
    await stream.aclose()


async def test_a_notification_reaches_only_its_recipients(
    user_a: User,
    user_b: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    stream_a = await _open(user_a, live_bus, sessionmaker, heartbeat=0.2)
    stream_b = await _open(user_b, live_bus, sessionmaker, heartbeat=0.2)
    await _next(stream_a)
    await _next(stream_b)

    live_bus.submit([notification_event(uuid.uuid4(), uuid.uuid4(), [user_a.id])])

    assert (await _next(stream_a)).startswith(b"event: invalidate\n")
    assert await _next(stream_b) == HEARTBEAT  # nothing for B, only its heartbeat
    await stream_a.aclose()
    await stream_b.aclose()


async def test_a_revoked_membership_stops_that_projects_events(
    authed_user: User,
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, "viewer")
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.2)
    await _next(stream)

    await db_session.execute(
        delete(ProjectMembership).where(ProjectMembership.user_id == authed_user.id)
    )
    await db_session.commit()
    await get_grant_cache().invalidate_user(authed_user.id)
    live_bus.submit([project_event(project.id)])

    assert await _next(stream) == HEARTBEAT
    await stream.aclose()


async def test_a_deactivated_user_is_disconnected_at_the_next_heartbeat(
    authed_user: User,
    db_session: AsyncSession,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.1)
    await _next(stream)

    authed_user.deleted_at = datetime.now(UTC)
    await db_session.commit()

    frames = [frame async for frame in stream]
    assert frames == []


async def test_the_stream_ends_at_its_maximum_lifetime(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.05, max_seconds=0.2)
    frames = [frame async for frame in stream]
    assert frames[0].startswith(b"event: ready\n")


async def test_a_resync_marker_is_forwarded(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    from app.live.fanout import QUEUE_SIZE

    stream = await _open(authed_user, live_bus, sessionmaker)
    await _next(stream)
    live_bus.submit([project_event(uuid.uuid4()) for _ in range(QUEUE_SIZE + 1)])

    assert (await _next(stream)).startswith(b"event: resync\n")
    await stream.aclose()
