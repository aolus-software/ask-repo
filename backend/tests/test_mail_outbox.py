"""The outbox: claim, send, mark — and the three ways a row does not get sent."""

import asyncio
import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.notifications import NotificationType
from app.mail.outbox import MAX_EMAIL_ATTEMPTS, send_pending_once
from app.mail.recording import RecordingMailSender
from app.mail.sender import MailSendError
from app.models import Notification, NotificationEvent, User
from app.repositories.notification import NotificationRepository
from app.services.notification_fanout import NotificationFanout


def _mail_on() -> Settings:
    return get_settings().model_copy(
        update={
            "mail_enabled": True,
            "smtp_host": "relay.internal",
            "smtp_from": "askrepo@example.com",
            "app_base_url": "https://askrepo.internal",
        }
    )


async def _pending(session: AsyncSession, user: User, project_id: uuid.UUID) -> Notification:
    await NotificationFanout(session, mail_enabled=True).raise_direct(
        event_type=NotificationType.MEMBERSHIP_GRANTED,
        project_id=project_id,
        actor_user_id=None,
        target_id=project_id,
        details={},
        recipient=user.id,
    )
    await session.commit()
    return (
        await session.scalars(select(Notification).where(Notification.user_id == user.id))
    ).one()


async def test_a_pending_row_is_sent_and_marked(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    row = await _pending(db_session, authed_user, project_id)
    sender = RecordingMailSender()

    assert (
        await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on()) == 1
    )

    [email] = sender.sent
    assert email.to == authed_user.email
    assert email.subject.startswith("[test] You were added to a project")
    await db_session.refresh(row)
    assert row.email_state == "sent"
    assert row.email_sent_at is not None


async def test_a_retryable_failure_stays_pending(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    row = await _pending(db_session, authed_user, project_id)
    sender = RecordingMailSender()
    sender.fail_with = MailSendError("421 try later", retryable=True)

    await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on())

    await db_session.refresh(row)
    assert row.email_state == "pending"
    assert row.email_attempts == 1


async def test_a_terminal_failure_is_failed_at_once(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    row = await _pending(db_session, authed_user, project_id)
    sender = RecordingMailSender()
    sender.fail_with = MailSendError("550 no such user", retryable=False)

    await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on())

    await db_session.refresh(row)
    assert row.email_state == "failed"


async def test_the_last_retryable_attempt_fails_the_row(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    row = await _pending(db_session, authed_user, project_id)
    await db_session.execute(
        update(Notification)
        .where(Notification.id == row.id)
        .values(email_attempts=MAX_EMAIL_ATTEMPTS - 1)
    )
    await db_session.commit()
    sender = RecordingMailSender()
    sender.fail_with = MailSendError("421 try later", retryable=True)

    await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on())

    await db_session.refresh(row)
    assert row.email_state == "failed"


async def test_a_row_older_than_a_day_is_skipped(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    row = await _pending(db_session, authed_user, project_id)
    await db_session.execute(
        update(NotificationEvent)
        .where(NotificationEvent.id == row.event_id)
        .values(created_at=datetime.now(UTC) - timedelta(hours=25))
    )
    await db_session.commit()
    sender = RecordingMailSender()

    await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on())

    assert sender.sent == []
    await db_session.refresh(row)
    assert row.email_state == "skipped"


async def test_a_deactivated_recipient_is_skipped(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    row = await _pending(db_session, authed_user, project_id)
    await db_session.execute(
        update(User).where(User.id == authed_user.id).values(deleted_at=datetime.now(UTC))
    )
    await db_session.commit()
    sender = RecordingMailSender()

    await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on())

    assert sender.sent == []
    await db_session.refresh(row)
    assert row.email_state == "skipped"


async def test_two_concurrent_claims_never_share_a_row(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    await _pending(db_session, authed_user, project_id)

    async def claim() -> list[uuid.UUID]:
        async with sessionmaker() as session:
            rows = await NotificationRepository(session).claim_pending_email(
                limit=50, lease=timedelta(minutes=2)
            )
            await session.commit()
            return [row.notification_id for row in rows]

    first, second = await asyncio.gather(claim(), claim())
    assert len(first) + len(second) == 1


async def test_a_claimed_row_is_not_reclaimed_before_its_lease_expires(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    project_id: uuid.UUID,
) -> None:
    await _pending(db_session, authed_user, project_id)
    repo = NotificationRepository(db_session)
    assert len(await repo.claim_pending_email(limit=50, lease=timedelta(minutes=2))) == 1
    await db_session.commit()
    assert await repo.claim_pending_email(limit=50, lease=timedelta(minutes=2)) == []


async def test_an_unrecognised_event_type_fails_that_row_without_blocking_the_batch(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    authed_user: User,
    user_a: User,
    project_id: uuid.UUID,
) -> None:
    good = await _pending(db_session, authed_user, project_id)
    bad = await _pending(db_session, user_a, project_id)
    await db_session.execute(
        update(NotificationEvent)
        .where(NotificationEvent.id == bad.event_id)
        .values(event_type="bogus.event")
    )
    await db_session.commit()
    sender = RecordingMailSender()

    assert (
        await send_pending_once(sessionmaker=sessionmaker, sender=sender, settings=_mail_on()) == 1
    )

    await db_session.refresh(good)
    await db_session.refresh(bad)
    assert good.email_state == "sent"
    assert bad.email_state == "failed"


def test_the_worker_starts_mail_loop_only_when_mail_is_on() -> None:
    """A structural check: `mail_loop` is appended under the switch, nowhere else."""
    import inspect

    import app.worker as worker

    source = inspect.getsource(worker.main)
    assert "if settings.mail_enabled:" in source
    assert source.count("mail_loop(") == 1
    assert "mail_loop" not in inspect.getsource(worker.reconcile_loop)
