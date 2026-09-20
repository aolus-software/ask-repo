"""The prune, and the cascade.

The cascade is the part worth a test: deleting an event must take its deliveries with
it, or the prune leaves orphan rows whose join returns nothing and whose unread count
never drops.
"""

import uuid
from datetime import UTC, datetime, timedelta

import pytest
from sqlalchemy import func, select, update
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications import NotificationType
from app.models.notification import Notification, NotificationEvent
from app.models.project import Project
from app.models.user import User
from app.repositories.notification_event import NotificationEventRepository
from app.services.notification_fanout import NotificationFanout


async def _create_old_notification(
    db_session: AsyncSession, *, user: User, project: Project, read: bool
) -> None:
    """Raise one real notification through the fan-out, then back-date its event past
    the retention window. Going through `NotificationFanout` exercises the actual
    write path — event row plus delivery row — rather than hand-building either.
    """
    await NotificationFanout(db_session).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        recipient=user.id,
        project_id=project.id,
        actor_user_id=None,
        target_id=project.id,
        details={"projectName": project.name, "roleName": "viewer"},
    )
    await db_session.flush()

    old_created_at = datetime.now(UTC) - timedelta(days=120)
    await db_session.execute(
        update(NotificationEvent)
        .where(NotificationEvent.project_id == project.id)
        .values(created_at=old_created_at)
    )
    if read:
        await db_session.execute(
            update(Notification)
            .where(Notification.user_id == user.id)
            .values(read_at=old_created_at)
        )
    await db_session.commit()


@pytest.fixture
async def old_notification(
    db_session: AsyncSession, authed_user: User, project_id: uuid.UUID
) -> None:
    """A 120-day-old, read notification and its event."""
    project = await db_session.get(Project, project_id)
    assert project is not None
    await _create_old_notification(db_session, user=authed_user, project=project, read=True)


@pytest.fixture
async def old_unread_notification(
    db_session: AsyncSession, authed_user: User, project_id: uuid.UUID
) -> None:
    """A 120-day-old, still-unread notification and its event."""
    project = await db_session.get(Project, project_id)
    assert project is not None
    await _create_old_notification(db_session, user=authed_user, project=project, read=False)


async def test_prune_removes_events_and_cascades_to_deliveries(
    db_session: AsyncSession, old_notification: None
) -> None:
    cutoff = datetime.now(UTC) - timedelta(days=30)
    pruned = await NotificationEventRepository(db_session).delete_older_than(cutoff)
    await db_session.commit()

    events = await db_session.execute(select(func.count()).select_from(NotificationEvent))
    rows = await db_session.execute(select(func.count()).select_from(Notification))
    assert pruned == 1
    assert events.scalar_one() == 0
    assert rows.scalar_one() == 0


async def test_prune_ignores_read_state(
    db_session: AsyncSession, old_unread_notification: None
) -> None:
    """A 90-day-old unread notification is not going to be acted on, and an unread
    badge that can never reach zero is a badge people stop looking at."""
    cutoff = datetime.now(UTC) - timedelta(days=30)
    assert await NotificationEventRepository(db_session).delete_older_than(cutoff) == 1
