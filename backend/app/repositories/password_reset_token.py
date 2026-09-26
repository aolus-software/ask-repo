"""Reset-token lookups. One live token per user; usable once; hard-deleted when dead."""

import uuid
from datetime import UTC, datetime, timedelta
from typing import Any, cast

from sqlalchemy import CursorResult, delete, or_, select, update

from app.models import PasswordResetToken
from app.repositories.base import BaseRepository

# How long a dead token lingers before the tick deletes it. Long enough that a user
# clicking yesterday's link gets "invalid or expired" rather than a lookup miss that
# looks the same anyway; short enough that hashes do not accumulate.
DEAD_TOKEN_GRACE = timedelta(days=1)


class PasswordResetTokenRepository(BaseRepository[PasswordResetToken]):
    model = PasswordResetToken

    async def revoke_live_for_user(self, user_id: uuid.UUID) -> int:
        """Revoke every unused, unrevoked, unexpired token — so an older link dies."""
        now = datetime.now(UTC)
        result = await self.session.execute(
            update(PasswordResetToken)
            .where(
                PasswordResetToken.user_id == user_id,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.revoked_at.is_(None),
                PasswordResetToken.expires_at > now,
            )
            .values(revoked_at=now)
        )
        return cast(CursorResult[Any], result).rowcount

    async def get_usable_by_hash(self, token_hash: str) -> PasswordResetToken | None:
        """The token, only if it can still be spent. Every other case is one `None`."""
        result = await self.session.execute(
            select(PasswordResetToken).where(
                PasswordResetToken.token_hash == token_hash,
                PasswordResetToken.used_at.is_(None),
                PasswordResetToken.revoked_at.is_(None),
                PasswordResetToken.expires_at > datetime.now(UTC),
            )
        )
        return result.scalar_one_or_none()

    async def mark_sent(self, token_id: uuid.UUID) -> None:
        await self.session.execute(
            update(PasswordResetToken)
            .where(PasswordResetToken.id == token_id)
            .values(sent_at=datetime.now(UTC))
        )

    async def delete_dead(self) -> int:
        """Hard-delete tokens expired, or used, more than a day ago."""
        cutoff = datetime.now(UTC) - DEAD_TOKEN_GRACE
        result = await self.session.execute(
            delete(PasswordResetToken).where(
                or_(PasswordResetToken.expires_at < cutoff, PasswordResetToken.used_at < cutoff)
            )
        )
        return cast(CursorResult[Any], result).rowcount
