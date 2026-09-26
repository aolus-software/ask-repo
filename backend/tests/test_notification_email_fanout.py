"""The email decision is a snapshot made inside the fan-out's transaction (spec §5.1)."""

import uuid

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.notifications import NotificationType
from app.models import Notification, NotificationPreference, User
from app.services.notification_fanout import NotificationFanout


async def _email_states(session: AsyncSession, user: User) -> list[str | None]:
    rows = await session.scalars(select(Notification).where(Notification.user_id == user.id))
    return [row.email_state for row in rows]


async def test_mail_on_marks_the_row_pending(
    db_session: AsyncSession, authed_user: User, project_id: uuid.UUID
) -> None:
    await NotificationFanout(db_session, mail_enabled=True).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={},
        recipient=authed_user.id,
    )
    await db_session.commit()
    assert await _email_states(db_session, authed_user) == ["pending"]


async def test_mail_off_leaves_email_out_of_play(
    db_session: AsyncSession, authed_user: User, project_id: uuid.UUID
) -> None:
    await NotificationFanout(db_session).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={},
        recipient=authed_user.id,
    )
    await db_session.commit()
    assert await _email_states(db_session, authed_user) == [None]


async def test_a_muted_email_preference_leaves_email_out_of_play(
    db_session: AsyncSession, authed_user: User, project_id: uuid.UUID
) -> None:
    db_session.add(
        NotificationPreference(
            id=uuid.uuid4(),
            user_id=authed_user.id,
            event_type=NotificationType.MEMBERSHIP_GRANTED.value,
            in_app=True,
            email=False,
        )
    )
    await db_session.commit()
    await NotificationFanout(db_session, mail_enabled=True).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={},
        recipient=authed_user.id,
    )
    await db_session.commit()
    assert await _email_states(db_session, authed_user) == [None]


async def test_muted_in_app_with_email_on_still_writes_a_pending_row(
    db_session: AsyncSession, authed_user: User, project_id: uuid.UUID
) -> None:
    """Rule 4's reason for existing: this combination must stay possible."""
    db_session.add(
        NotificationPreference(
            id=uuid.uuid4(),
            user_id=authed_user.id,
            event_type=NotificationType.MEMBERSHIP_GRANTED.value,
            in_app=False,
            email=True,
        )
    )
    await db_session.commit()
    await NotificationFanout(db_session, mail_enabled=True).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={},
        recipient=authed_user.id,
    )
    await db_session.commit()
    [row] = await db_session.scalars(
        select(Notification).where(Notification.user_id == authed_user.id)
    )
    assert row.in_app_visible is False
    assert row.email_state == "pending"
