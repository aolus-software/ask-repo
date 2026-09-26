"""The reset flow's policy, below the route: enumeration, single use, sessions, audit."""

import uuid
from collections.abc import Awaitable, Callable
from datetime import UTC, datetime, timedelta
from typing import Any

import pytest
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings, get_settings
from app.core.audit import AuditEventType, AuditRecorder
from app.core.errors import AppError, ErrorCode
from app.core.security import generate_opaque_token, hash_password, sha256_hex, verify_password
from app.mail.recording import RecordingMailSender
from app.mail.sender import MailSendError
from app.models import PasswordResetToken, RefreshToken, User
from app.schemas.password_reset import PasswordResetConfirm, PasswordResetRequest
from app.services.password_reset import PasswordResetService, deliver_password_reset

NEW_PASSWORD = "another-entirely-fine-passphrase"


def _mail_on() -> Settings:
    return get_settings().model_copy(
        update={
            "mail_enabled": True,
            "smtp_host": "relay.internal",
            "smtp_from": "askrepo@example.com",
            "app_base_url": "https://askrepo.internal",
        }
    )


async def _user(session: AsyncSession, *, must_change: bool = False) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email="dev@example.com",
        password_hash=hash_password("a-perfectly-fine-passphrase", cost=4),
        must_change_password=must_change,
    )
    session.add(user)
    await session.commit()
    return user


def _service(
    session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession], settings: Settings
) -> PasswordResetService:
    return PasswordResetService(session, settings, recorder=AuditRecorder(sessionmaker))


async def test_mail_off_refuses_and_writes_nothing(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _user(db_session)
    service = _service(db_session, sessionmaker, get_settings())
    with pytest.raises(AppError) as raised:
        await service.request(PasswordResetRequest(email="dev@example.com"))
    assert raised.value.status_code == 409
    count = await db_session.scalar(select(func.count()).select_from(PasswordResetToken))
    assert count == 0


async def test_an_unknown_address_returns_nothing_and_audits_anonymously(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    audit_rows: Callable[..., Awaitable[list[Any]]],
) -> None:
    service = _service(db_session, sessionmaker, _mail_on())
    assert await service.request(PasswordResetRequest(email="nobody@example.com")) is None
    [row] = await audit_rows(event_type=AuditEventType.AUTH_PASSWORD_RESET_REQUESTED.value)
    assert row.actor_user_id is None
    assert row.actor_email is None
    assert row.details == {"unknownAccount": True}


async def test_a_known_address_stores_only_the_hash(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    audit_rows: Callable[..., Awaitable[list[Any]]],
) -> None:
    user = await _user(db_session)
    pending = await _service(db_session, sessionmaker, _mail_on()).request(
        PasswordResetRequest(email="Dev@Example.com")
    )
    assert pending is not None
    assert pending.to == "dev@example.com"
    stored = (await db_session.scalars(select(PasswordResetToken))).one()
    assert stored.token_hash == sha256_hex(pending.raw_token)
    assert pending.raw_token not in {stored.token_hash, str(stored.id)}
    [row] = await audit_rows(event_type=AuditEventType.AUTH_PASSWORD_RESET_REQUESTED.value)
    assert row.actor_user_id == user.id
    assert row.details == {"unknownAccount": False}


async def test_a_second_request_revokes_the_first(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _user(db_session)
    service = _service(db_session, sessionmaker, _mail_on())
    first = await service.request(PasswordResetRequest(email="dev@example.com"))
    second = await service.request(PasswordResetRequest(email="dev@example.com"))
    assert first is not None and second is not None

    with pytest.raises(AppError) as raised:
        await service.confirm(
            PasswordResetConfirm(token=first.raw_token, new_password=NEW_PASSWORD)
        )
    assert raised.value.status_code == 400
    await service.confirm(PasswordResetConfirm(token=second.raw_token, new_password=NEW_PASSWORD))


async def test_confirm_sets_the_password_clears_the_flag_and_ends_every_session(
    db_session: AsyncSession,
    sessionmaker: async_sessionmaker[AsyncSession],
    audit_rows: Callable[..., Awaitable[list[Any]]],
) -> None:
    user = await _user(db_session, must_change=True)
    now = datetime.now(UTC)
    db_session.add_all(
        RefreshToken(
            id=uuid.uuid4(),
            user_id=user.id,
            family_id=uuid.uuid4(),
            token_hash=sha256_hex(generate_opaque_token()),
            issued_at=now,
            expires_at=now + timedelta(days=30),
        )
        for _ in range(2)
    )
    await db_session.commit()
    service = _service(db_session, sessionmaker, _mail_on())
    pending = await service.request(PasswordResetRequest(email="dev@example.com"))
    assert pending is not None

    await service.confirm(PasswordResetConfirm(token=pending.raw_token, new_password=NEW_PASSWORD))

    await db_session.refresh(user)
    assert verify_password(NEW_PASSWORD, user.password_hash)
    assert user.must_change_password is False
    live = await db_session.scalar(
        select(func.count())
        .select_from(RefreshToken)
        .where(RefreshToken.user_id == user.id, RefreshToken.revoked_at.is_(None))
    )
    assert live == 0
    [row] = await audit_rows(event_type=AuditEventType.AUTH_PASSWORD_RESET_COMPLETED.value)
    assert row.actor_user_id == user.id
    assert row.details == {"revokedCount": 2}


async def test_a_token_works_once(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _user(db_session)
    service = _service(db_session, sessionmaker, _mail_on())
    pending = await service.request(PasswordResetRequest(email="dev@example.com"))
    assert pending is not None
    confirm = PasswordResetConfirm(token=pending.raw_token, new_password=NEW_PASSWORD)
    await service.confirm(confirm)
    with pytest.raises(AppError) as raised:
        await service.confirm(confirm)
    assert raised.value.code == ErrorCode.PASSWORD_RESET_TOKEN_INVALID


async def test_a_weak_password_is_refused_and_the_token_survives(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _user(db_session)
    service = _service(db_session, sessionmaker, _mail_on())
    pending = await service.request(PasswordResetRequest(email="dev@example.com"))
    assert pending is not None
    with pytest.raises(AppError) as raised:
        await service.confirm(PasswordResetConfirm(token=pending.raw_token, new_password="short"))
    assert raised.value.code == ErrorCode.WEAK_PASSWORD
    await service.confirm(PasswordResetConfirm(token=pending.raw_token, new_password=NEW_PASSWORD))


async def test_delivery_sends_once_and_stamps_sent_at(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _user(db_session)
    settings = _mail_on()
    pending = await _service(db_session, sessionmaker, settings).request(
        PasswordResetRequest(email="dev@example.com")
    )
    assert pending is not None
    sender = RecordingMailSender()

    await deliver_password_reset(
        pending, sender=sender, settings=settings, sessionmaker=sessionmaker
    )

    [email] = sender.sent
    assert f"#token={pending.raw_token}" in email.body
    stored = (await db_session.scalars(select(PasswordResetToken))).one()
    await db_session.refresh(stored)
    assert stored.sent_at is not None


async def test_a_failed_delivery_never_raises_and_leaves_sent_at_null(
    db_session: AsyncSession, sessionmaker: async_sessionmaker[AsyncSession]
) -> None:
    await _user(db_session)
    settings = _mail_on()
    pending = await _service(db_session, sessionmaker, settings).request(
        PasswordResetRequest(email="dev@example.com")
    )
    assert pending is not None
    sender = RecordingMailSender()
    sender.fail_with = MailSendError("relay down", retryable=True)

    await deliver_password_reset(
        pending, sender=sender, settings=settings, sessionmaker=sessionmaker
    )

    stored = (await db_session.scalars(select(PasswordResetToken))).one()
    await db_session.refresh(stored)
    assert stored.sent_at is None
