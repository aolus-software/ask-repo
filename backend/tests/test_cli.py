"""The bootstrap seed.

`docs/PRD.md` §7 requires bringing up a fresh instance with no manual database work, so
this must be automatic and safe to re-run: the container entrypoint invokes it on every
start.
"""

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

from app.cli import seed_admins
from app.config import get_settings


@pytest.fixture(autouse=True)
def _bootstrap_password() -> Iterator[None]:
    """The seed refuses to run without a password; most tests want one set."""
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "a-perfectly-fine-passphrase")
        get_settings.cache_clear()
        yield
    get_settings.cache_clear()


async def test_seeding_creates_both_bootstrap_admins(db_session: AsyncSession) -> None:
    created = await seed_admins()

    assert created == 2
    result = await db_session.execute(
        text("SELECT count(*) FROM users WHERE is_admin IS TRUE AND deleted_at IS NULL")
    )
    assert result.scalar_one() == 2


async def test_seeded_admins_must_change_their_password(db_session: AsyncSession) -> None:
    """SECURITY.md:54 tells the operator to change them; the flag enforces it."""
    await seed_admins()

    result = await db_session.execute(
        text("SELECT bool_and(must_change_password) FROM users WHERE is_admin IS TRUE")
    )
    assert result.scalar_one() is True


async def test_seeding_twice_creates_nothing_the_second_time(db_session: AsyncSession) -> None:
    """The entrypoint runs this on every container start."""
    await seed_admins()

    second = await seed_admins()

    assert second == 0
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 2


async def test_the_stored_password_is_hashed_not_plaintext(db_session: AsyncSession) -> None:
    await seed_admins()

    result = await db_session.execute(text("SELECT password_hash FROM users LIMIT 1"))
    stored = result.scalar_one()
    assert stored.startswith("$2b$")
    assert "a-perfectly-fine-passphrase" not in stored


async def test_seeding_refuses_without_a_password(db_session: AsyncSession) -> None:
    """A silent weak-password seed is worse than a failed boot."""
    with pytest.MonkeyPatch.context() as patch:
        patch.delenv("BOOTSTRAP_ADMIN_PASSWORD", raising=False)
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="BOOTSTRAP_ADMIN_PASSWORD"):
            await seed_admins()

    get_settings.cache_clear()
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 0


async def test_seeding_refuses_a_password_failing_policy(db_session: AsyncSession) -> None:
    with pytest.MonkeyPatch.context() as patch:
        patch.setenv("BOOTSTRAP_ADMIN_PASSWORD", "short")
        get_settings.cache_clear()

        with pytest.raises(ValueError, match="policy"):
            await seed_admins()

    get_settings.cache_clear()
    result = await db_session.execute(text("SELECT count(*) FROM users"))
    assert result.scalar_one() == 0


async def test_a_soft_deleted_bootstrap_admin_is_reseeded(db_session: AsyncSession) -> None:
    """Otherwise deactivating the seeded admin leaves no recovery path."""
    await seed_admins()
    await db_session.execute(text("UPDATE users SET deleted_at = now()"))
    await db_session.commit()

    created = await seed_admins()

    assert created == 2
