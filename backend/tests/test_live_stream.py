"""The `/events` generator: ready first, access re-checked per event, closed on deactivation."""

import asyncio
import uuid
from collections.abc import AsyncGenerator, AsyncIterator
from datetime import UTC, datetime

import pytest
from httpx import AsyncClient
from sqlalchemy import delete
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import get_settings
from app.core.grant_cache import get_grant_cache
from app.core.middleware import load_authenticated_user
from app.core.security import decode_access_claims
from app.live.bus import InMemoryLiveEventBus
from app.live.events import notification_event, project_event
from app.live.stream import HEARTBEAT, live_event_stream
from app.models import User
from app.models.membership import ProjectMembership
from app.repositories.refresh_token import RefreshTokenRepository
from tests.conftest import TEST_PASSWORD, GrantMembership
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


async def test_a_revoked_session_closes_its_stream_at_the_next_heartbeat(
    client: AsyncClient,
    authed_user: User,
    db_session: AsyncSession,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Logout, "sign out this session", and a password change revoking other sessions
    all work by revoking a refresh-token family. None of them touch the still-valid
    access token an open `/events` stream was built from, so the stream has to notice
    on its own (F2)."""
    login = await client.post(
        "/auth/login", json={"email": authed_user.email, "password": TEST_PASSWORD}
    )
    assert login.status_code == 200
    claims = decode_access_claims(login.json()["accessToken"], secret=get_settings().secret_key)
    assert claims.session_id is not None

    async with sessionmaker() as session:
        actor = await load_authenticated_user(session, authed_user.id, claims.session_id)
    assert actor is not None

    stream = live_event_stream(
        user=actor,
        hub=live_bus,
        sessionmaker=sessionmaker,
        heartbeat_seconds=0.1,
        max_seconds=30,
    )
    await _next(stream)  # ready

    await RefreshTokenRepository(db_session).revoke_family(claims.session_id, reason="logout")
    await db_session.commit()

    frames = [frame async for frame in stream]
    assert frames == []


async def test_a_token_minted_before_sessions_skips_the_session_check(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A `None` `session_id` — a token minted before the `sid` claim existed — is not
    "no session"; it must not be treated as revoked."""
    async with sessionmaker() as session:
        actor = await load_authenticated_user(session, authed_user.id, None)
    assert actor is not None
    assert actor.session_id is None

    stream = live_event_stream(
        user=actor,
        hub=live_bus,
        sessionmaker=sessionmaker,
        heartbeat_seconds=0.1,
        max_seconds=0.35,
    )

    frames = [frame async for frame in stream]
    assert frames[0].startswith(b"event: ready\n")
    assert HEARTBEAT in frames


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


async def test_close_all_ends_an_open_stream(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """The hub's own way of saying "the broker is gone for good" (F3): every open
    stream ends so its client reconnects, gets `503`, and falls back to polling."""
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=5, max_seconds=30)
    await _next(stream)  # ready

    live_bus.close_all()

    frames = [frame async for frame in stream]
    assert frames == []


async def test_a_failing_recheck_closes_the_stream_without_raising(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A re-check that raises must not propagate out of the generator (F4): the stream
    just ends, and the client reconnects."""

    async def _boom(*args: object, **kwargs: object) -> None:
        raise RuntimeError("database exploded")

    monkeypatch.setattr("app.live.stream.load_authenticated_user", _boom)

    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=0.05, max_seconds=5)
    await _next(stream)  # ready

    frames = [frame async for frame in stream]
    assert frames == []


async def test_two_events_within_the_reuse_window_recheck_once(
    authed_user: User,
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two project-scoped events arriving inside `_RECHECK_REUSE_SECONDS` reload the
    caller once, not twice (F4) — the pool must not take one query per open stream per
    event."""
    project = await create_project(db_session, grant_owner=False)
    await db_session.commit()
    await grant_membership(authed_user.id, project.id, "viewer")

    calls = 0
    real = load_authenticated_user

    async def _counting(
        session: AsyncSession, user_id: uuid.UUID, session_id: uuid.UUID | None
    ) -> object:
        nonlocal calls
        calls += 1
        return await real(session, user_id, session_id)

    monkeypatch.setattr("app.live.stream.load_authenticated_user", _counting)

    # A heartbeat long enough that only the two events drive a re-check.
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=10, max_seconds=30)
    await _next(stream)  # ready

    live_bus.submit([project_event(project.id)])
    await _next(stream)
    live_bus.submit([project_event(project.id)])
    await _next(stream)

    assert calls == 1
    await stream.aclose()


async def test_heartbeat_is_not_starved_by_invisible_traffic(
    authed_user: User,
    live_bus: InMemoryLiveEventBus,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """A queue kept busy by events this caller may not see must not delay the
    `: ping` (F6): it is due every `heartbeat_seconds`, not every `heartbeat_seconds`
    of quiet."""
    heartbeat = 0.2
    stream = await _open(authed_user, live_bus, sessionmaker, heartbeat=heartbeat, max_seconds=3)
    await _next(stream)  # ready

    async def _flood() -> None:
        while True:
            live_bus.submit([project_event(uuid.uuid4())])
            await asyncio.sleep(0.01)

    flooder = asyncio.create_task(_flood())
    started = asyncio.get_event_loop().time()
    try:
        frame = b""
        while frame != HEARTBEAT:
            frame = await _next(stream)
    finally:
        flooder.cancel()
        try:
            await flooder
        except asyncio.CancelledError:
            pass
    elapsed = asyncio.get_event_loop().time() - started

    assert elapsed <= heartbeat * 1.5
    await stream.aclose()


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
