"""Reset tokens: one live per user, usable once, hard-deleted when dead."""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.security import hash_password
from app.models import PasswordResetToken, User
from app.repositories.password_reset_token import PasswordResetTokenRepository


async def _user(session: AsyncSession) -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=f"{uuid.uuid4().hex}@example.com",
        password_hash=hash_password("a-perfectly-fine-passphrase", cost=4),
    )
    session.add(user)
    await session.commit()
    return user


def _token(
    user: User, *, hash_: str, expires_in: timedelta = timedelta(minutes=30)
) -> PasswordResetToken:
    now = datetime.now(UTC)
    return PasswordResetToken(
        id=uuid.uuid4(),
        user_id=user.id,
        token_hash=hash_,
        created_at=now,
        expires_at=now + expires_in,
    )


async def test_revoking_leaves_only_new_tokens_usable(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    repo = PasswordResetTokenRepository(db_session)
    await repo.add(_token(user, hash_="a" * 64))
    assert await repo.revoke_live_for_user(user.id) == 1
    await repo.add(_token(user, hash_="b" * 64))
    await db_session.commit()

    assert await repo.get_usable_by_hash("a" * 64) is None
    assert await repo.get_usable_by_hash("b" * 64) is not None


async def test_expired_and_used_tokens_are_not_usable(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    repo = PasswordResetTokenRepository(db_session)
    await repo.add(_token(user, hash_="c" * 64, expires_in=timedelta(seconds=-1)))
    used = await repo.add(_token(user, hash_="d" * 64))
    used.used_at = datetime.now(UTC)
    await db_session.commit()

    assert await repo.get_usable_by_hash("c" * 64) is None
    assert await repo.get_usable_by_hash("d" * 64) is None


async def test_mark_sent_stamps_the_row(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    repo = PasswordResetTokenRepository(db_session)
    token = await repo.add(_token(user, hash_="e" * 64))
    await repo.mark_sent(token.id)
    await db_session.commit()
    await db_session.refresh(token)
    assert token.sent_at is not None


async def test_dead_tokens_are_hard_deleted_after_a_day(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    repo = PasswordResetTokenRepository(db_session)
    await repo.add(_token(user, hash_="f" * 64, expires_in=timedelta(days=-2)))
    await repo.add(_token(user, hash_="0" * 64, expires_in=timedelta(minutes=-5)))
    await repo.add(_token(user, hash_="1" * 64))
    await db_session.commit()

    assert await repo.delete_dead() == 1
    await db_session.commit()
    assert await repo.get_usable_by_hash("1" * 64) is not None


async def test_id_defaults_to_uuid4_when_not_provided(db_session: AsyncSession) -> None:
    user = await _user(db_session)
    repo = PasswordResetTokenRepository(db_session)
    now = datetime.now(UTC)
    # Construct token without passing id — relies on default=uuid.uuid4
    token = PasswordResetToken(
        user_id=user.id,
        token_hash="g" * 64,
        created_at=now,
        expires_at=now + timedelta(minutes=30),
    )
    added = await repo.add(token)
    assert isinstance(added.id, uuid.UUID)
    await db_session.commit()
