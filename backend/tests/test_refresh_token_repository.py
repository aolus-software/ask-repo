"""Rotation-chain queries.

`family_id` is what makes replay detection revoke exactly one device rather than
logging the user out everywhere, so these tests are mostly about blast radius.
"""

import uuid
from datetime import UTC, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import User
from app.repositories.refresh_token import RefreshTokenRepository


async def _make_user(session: AsyncSession, email: str = "dev@example.com") -> User:
    user = User(
        id=uuid.uuid4(),
        name="Dev",
        email=email,
        password_hash="$2b$04$placeholderplaceholderplaceholderplaceholderplaceholderxx",
        must_change_password=False,
    )
    session.add(user)
    await session.commit()
    return user


def _expiry() -> datetime:
    return datetime.now(UTC) + timedelta(days=30)


async def test_create_then_find_by_hash(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)

    created = await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="a" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    found = await repository.get_by_hash("a" * 64)
    assert found is not None
    assert found.id == created.id


async def test_unknown_hash_returns_none(db_session: AsyncSession) -> None:
    repository = RefreshTokenRepository(db_session)

    assert (await repository.get_by_hash("b" * 64)) is None


async def test_mark_used_stamps_the_timestamp(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    token = await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="c" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    await repository.mark_used(token)
    await db_session.commit()

    assert token.used_at is not None


async def test_revoke_family_hits_every_token_in_that_family_only(
    db_session: AsyncSession,
) -> None:
    """A replay must not log the user out of their other devices."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    compromised = uuid.uuid4()
    other = uuid.uuid4()
    for index, family in enumerate([compromised, compromised, other]):
        await repository.create(
            user_id=user.id,
            family_id=family,
            token_hash=str(index) * 64,
            expires_at=_expiry(),
        )
    await db_session.commit()

    revoked = await repository.revoke_family(compromised, reason="replay")
    await db_session.commit()

    assert revoked == 2
    survivor = await repository.get_by_hash("2" * 64)
    assert survivor is not None
    assert survivor.revoked_at is None


async def test_revoke_family_records_the_reason(db_session: AsyncSession) -> None:
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    family = uuid.uuid4()
    await repository.create(
        user_id=user.id, family_id=family, token_hash="d" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    await repository.revoke_family(family, reason="replay")
    await db_session.commit()

    token = await repository.get_by_hash("d" * 64)
    assert token is not None
    assert token.revoked_reason == "replay"


async def test_revoke_family_does_not_re_revoke(db_session: AsyncSession) -> None:
    """Otherwise a second replay overwrites the original reason and timestamp."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    family = uuid.uuid4()
    await repository.create(
        user_id=user.id, family_id=family, token_hash="e" * 64, expires_at=_expiry()
    )
    await db_session.commit()
    await repository.revoke_family(family, reason="logout")
    await db_session.commit()

    second = await repository.revoke_family(family, reason="replay")
    await db_session.commit()

    assert second == 0
    token = await repository.get_by_hash("e" * 64)
    assert token is not None
    assert token.revoked_reason == "logout"


async def test_revoke_all_for_user_can_spare_the_caller(db_session: AsyncSession) -> None:
    """change-password revokes all *other* sessions (docs/PRD.md:108)."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    keep = await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="f" * 64, expires_at=_expiry()
    )
    await repository.create(
        user_id=user.id, family_id=uuid.uuid4(), token_hash="0" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    revoked = await repository.revoke_all_for_user(
        user.id, reason="password_change", except_token_id=keep.id
    )
    await db_session.commit()

    assert revoked == 1
    spared = await repository.get_by_hash("f" * 64)
    assert spared is not None
    assert spared.revoked_at is None


async def test_revoke_all_for_user_leaves_other_users_alone(db_session: AsyncSession) -> None:
    first = await _make_user(db_session, "first@example.com")
    second = await _make_user(db_session, "second@example.com")
    repository = RefreshTokenRepository(db_session)
    await repository.create(
        user_id=first.id, family_id=uuid.uuid4(), token_hash="1" * 64, expires_at=_expiry()
    )
    await repository.create(
        user_id=second.id, family_id=uuid.uuid4(), token_hash="3" * 64, expires_at=_expiry()
    )
    await db_session.commit()

    await repository.revoke_all_for_user(first.id, reason="logout_all")
    await db_session.commit()

    untouched = await repository.get_by_hash("3" * 64)
    assert untouched is not None
    assert untouched.revoked_at is None


async def test_siblings_can_coexist_in_one_family(db_session: AsyncSession) -> None:
    """The grace window mints a sibling rather than reusing a stored raw token (D12)."""
    user = await _make_user(db_session)
    repository = RefreshTokenRepository(db_session)
    family = uuid.uuid4()
    for index in range(2):
        await repository.create(
            user_id=user.id,
            family_id=family,
            token_hash=f"{index}" * 64,
            expires_at=_expiry(),
        )
    await db_session.commit()

    result = await db_session.execute(
        text("SELECT count(*) FROM refresh_tokens WHERE family_id = :family"),
        {"family": family},
    )
    assert result.scalar_one() == 2
