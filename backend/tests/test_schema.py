"""What the migration actually produced.

These assert against the live database rather than the model definitions, because a
model and a hand-written migration can disagree — and the migration is what runs.
"""

import subprocess
from pathlib import Path

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncSession

BACKEND_ROOT = Path(__file__).resolve().parent.parent


async def test_users_email_is_unique_only_among_live_rows(db_session: AsyncSession) -> None:
    """Soft-deleting an account frees its address for reuse (D20)."""
    await db_session.execute(
        text(
            "INSERT INTO users (id, name, email, password_hash, deleted_at)"
            " VALUES (gen_random_uuid(), 'A', 'a@example.com', 'x', now())"
        )
    )
    await db_session.execute(
        text(
            "INSERT INTO users (id, name, email, password_hash)"
            " VALUES (gen_random_uuid(), 'B', 'a@example.com', 'x')"
        )
    )
    await db_session.commit()

    live = await db_session.execute(
        text("SELECT count(*) FROM users WHERE email = 'a@example.com' AND deleted_at IS NULL")
    )
    assert live.scalar_one() == 1


async def test_two_live_rows_cannot_share_an_email(db_session: AsyncSession) -> None:
    from sqlalchemy.exc import IntegrityError

    try:
        # The index is not deferrable, so Postgres raises on the second INSERT
        # itself rather than waiting for commit(); both must be inside the try.
        for _ in range(2):
            await db_session.execute(
                text(
                    "INSERT INTO users (id, name, email, password_hash)"
                    " VALUES (gen_random_uuid(), 'A', 'dup@example.com', 'x')"
                )
            )
        await db_session.commit()
    except IntegrityError:
        return
    raise AssertionError("expected the partial unique index to reject a duplicate live email")


async def test_timestamps_are_timezone_aware(db_session: AsyncSession) -> None:
    """`docs/PRD.md:321` requires timestamptz; a naive column loses the offset."""
    result = await db_session.execute(
        text(
            "SELECT data_type FROM information_schema.columns"
            " WHERE table_name = 'users' AND column_name = 'created_at'"
        )
    )
    assert result.scalar_one() == "timestamp with time zone"


async def test_refresh_tokens_has_no_deleted_at(db_session: AsyncSession) -> None:
    """D14: its lifecycle is revoked_at/expires_at. A third state column would rot."""
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM information_schema.columns"
            " WHERE table_name = 'refresh_tokens' AND column_name = 'deleted_at'"
        )
    )
    assert result.scalar_one() == 0


async def test_token_hash_is_unique(db_session: AsyncSession) -> None:
    result = await db_session.execute(
        text(
            "SELECT count(*) FROM pg_indexes"
            " WHERE tablename = 'refresh_tokens' AND indexname = 'uq_refresh_tokens_token_hash'"
        )
    )
    assert result.scalar_one() == 1


async def test_downgrade_then_upgrade_is_clean() -> None:
    """A migration that cannot be reversed cannot be iterated on safely."""
    for args in (["downgrade", "base"], ["upgrade", "head"]):
        subprocess.run(["uv", "run", "alembic", *args], cwd=BACKEND_ROOT, check=True)
