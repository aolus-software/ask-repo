"""The write path.

Three properties are load-bearing and none of them is visible from a single file:
fan-out is atomic with the state change that caused it; a muted recipient still gets a
row; and an event with no audience is still recorded.
"""

import uuid

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications import NotificationType
from app.models.notification import Notification, NotificationEvent
from app.models.user import User
from app.repositories.notification_preference import NotificationPreferenceRepository
from app.services.notification_fanout import NotificationFanout
from tests.conftest import GrantMembership


async def test_fan_out_writes_one_event_and_one_row_per_recipient(
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    user_a: User,
    user_b: User,
    project_id: uuid.UUID,
) -> None:
    await grant_membership(user_a.id, project_id, "owner")
    await grant_membership(user_b.id, project_id, "viewer")

    await NotificationFanout(db_session).raise_event(
        event_type=NotificationType.PROJECT_READY,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={"projectName": "api", "fileCount": 3, "chunkCount": 9},
    )
    await db_session.commit()

    events = await db_session.execute(select(func.count()).select_from(NotificationEvent))
    rows = await db_session.execute(select(Notification.user_id))
    assert events.scalar_one() == 1
    assert set(rows.scalars().all()) == {user_a.id, user_b.id}


async def test_a_muted_recipient_still_gets_a_row_marked_invisible(
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    user_a: User,
    project_id: uuid.UUID,
) -> None:
    """The row *is* the record, and Phase 2.4's email is a delivery attempt against
    it. Suppressing it would leave a user who muted in-app but wants email with
    nothing to email against — the exact divergence "one record, two transports"
    exists to prevent."""
    await grant_membership(user_a.id, project_id, "owner")
    await NotificationPreferenceRepository(db_session).upsert_many(
        user_a.id, {NotificationType.PROJECT_READY.value: (False, True)}
    )
    await db_session.flush()

    await NotificationFanout(db_session).raise_event(
        event_type=NotificationType.PROJECT_READY,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={"projectName": "api", "fileCount": 3, "chunkCount": 9},
    )
    await db_session.commit()

    row = await db_session.execute(select(Notification).where(Notification.user_id == user_a.id))
    assert row.scalar_one().in_app_visible is False


async def test_zero_recipients_still_writes_the_event_row(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    await NotificationFanout(db_session).raise_event(
        event_type=NotificationType.PROJECT_READY,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={"projectName": "api", "fileCount": 3, "chunkCount": 9},
    )
    await db_session.commit()

    events = await db_session.execute(select(func.count()).select_from(NotificationEvent))
    rows = await db_session.execute(select(func.count()).select_from(Notification))
    assert events.scalar_one() == 1
    assert rows.scalar_one() == 0


async def test_raise_direct_writes_exactly_one_row_for_the_named_recipient(
    db_session: AsyncSession, user_a: User, project_id: uuid.UUID
) -> None:
    """`membership.granted`'s recipient was not a member when the event was raised, so
    it cannot come from the permission map."""
    await NotificationFanout(db_session).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        recipient=user_a.id,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={"projectName": "api", "roleName": "editor"},
    )
    await db_session.commit()

    rows = await db_session.execute(select(Notification.user_id))
    assert list(rows.scalars().all()) == [user_a.id]


async def test_fan_out_does_not_commit(
    db_session: AsyncSession,
    grant_membership: GrantMembership,
    user_a: User,
    project_id: uuid.UUID,
) -> None:
    """Approach A: the caller owns the transaction, so a rollback takes the
    notification with the state change it described."""
    await grant_membership(user_a.id, project_id, "owner")
    await NotificationFanout(db_session).raise_event(
        event_type=NotificationType.PROJECT_READY,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={"projectName": "api", "fileCount": 3, "chunkCount": 9},
    )
    await db_session.rollback()

    events = await db_session.execute(select(func.count()).select_from(NotificationEvent))
    assert events.scalar_one() == 0


async def test_a_key_nobody_named_is_refused(
    db_session: AsyncSession, project_id: uuid.UUID
) -> None:
    with pytest.raises(ValueError, match="repoUrl"):
        await NotificationFanout(db_session).raise_event(
            event_type=NotificationType.PROJECT_READY,
            project_id=project_id,
            actor_user_id=None,
            target_id=project_id,
            details={"repoUrl": "https://host/x.git"},
        )
