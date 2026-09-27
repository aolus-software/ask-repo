"""Live events leave only on commit.

`stage_live_event` queues an event on the session; the `after_commit` hook hands the queue
to the process's publisher and `after_rollback` discards it. These tests pin that a
rolled-back change never announces itself and that a broken publisher never fails the
write it rides on.
"""

import uuid
from collections.abc import Sequence

import pytest
from sqlalchemy.ext.asyncio import AsyncSession

from app.live.bus import InMemoryLiveEventBus
from app.live.events import LiveEvent, notification_event, project_event
from app.live.staging import set_live_publisher, stage_live_event


async def test_commit_publishes_staged_events(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    event = project_event(uuid.uuid4())
    stage_live_event(db_session, event)
    assert live_bus.published == []

    await db_session.commit()

    assert live_bus.published == [event]


async def test_rollback_publishes_nothing(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    stage_live_event(db_session, project_event(uuid.uuid4()))

    await db_session.rollback()
    await db_session.commit()

    assert live_bus.published == []


async def test_duplicates_in_one_transaction_collapse(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    project_id = uuid.uuid4()
    stage_live_event(db_session, project_event(project_id))
    stage_live_event(db_session, project_event(project_id))

    await db_session.commit()

    assert live_bus.published == [project_event(project_id)]


async def test_a_failing_publisher_never_fails_the_commit(
    db_session: AsyncSession, caplog: pytest.LogCaptureFixture
) -> None:
    class Broken:
        def submit(self, events: Sequence[LiveEvent]) -> None:
            raise RuntimeError("broker gone")

    set_live_publisher(Broken())
    stage_live_event(db_session, project_event(uuid.uuid4()))

    await db_session.commit()

    assert "live event publish failed" in caplog.text


async def test_a_closed_session_discards_what_it_staged(
    db_session: AsyncSession, live_bus: InMemoryLiveEventBus
) -> None:
    """`after_transaction_end` (F9), not `after_soft_rollback`: closing a session ends
    its outermost transaction the same way a rollback does, and staged events must not
    survive to be published by an unrelated commit that happens to reuse the session
    later."""
    stage_live_event(db_session, project_event(uuid.uuid4()))

    await db_session.close()
    await db_session.commit()

    assert live_bus.published == []


def test_an_event_round_trips_through_bytes() -> None:
    event = notification_event(uuid.uuid4(), uuid.uuid4(), [uuid.uuid4(), uuid.uuid4()])
    assert LiveEvent.from_bytes(event.to_bytes()) == event
