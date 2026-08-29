"""Queries over `refresh_tokens`.

`refresh_tokens` carries no `deleted_at` (D14), so `active_select()` returns a plain
select here — which is why the base method checks for the mixin rather than assuming it.

Only the SHA-256 of a token is ever stored or compared. The raw value lives in the
response cookie and nowhere else.
"""

import uuid
from datetime import UTC, datetime
from typing import Any, cast

from sqlalchemy import delete, or_, update
from sqlalchemy.engine import CursorResult

from app.models.refresh_token import RefreshToken, RevokedReason
from app.repositories.base import BaseRepository


class RefreshTokenRepository(BaseRepository[RefreshToken]):
    """Issue, consume, and revoke refresh tokens."""

    model = RefreshToken

    async def get_by_hash(self, token_hash: str) -> RefreshToken | None:
        """Find a token by its stored digest. Hits the unique index."""
        result = await self.session.execute(
            self.active_select().where(RefreshToken.token_hash == token_hash)
        )
        return result.scalar_one_or_none()

    async def create(
        self,
        *,
        user_id: uuid.UUID,
        family_id: uuid.UUID,
        token_hash: str,
        expires_at: datetime,
    ) -> RefreshToken:
        """Insert a token. A rotation successor reuses the parent's `family_id`."""
        token = RefreshToken(
            id=uuid.uuid4(),
            user_id=user_id,
            family_id=family_id,
            token_hash=token_hash,
            issued_at=datetime.now(UTC),
            expires_at=expires_at,
        )
        return await self.add(token)

    async def mark_used(self, token: RefreshToken) -> None:
        """Record that this token has been exchanged. Not the same as revoking it.

        `revoked_at` is left untouched — the family is still live — but
        `revoked_reason` is set to `"rotated"` per the spec's revocation matrix, so the
        audit column can tell "consumed by normal rotation" apart from "never used".
        """
        token.used_at = datetime.now(UTC)
        token.revoked_reason = "rotated"
        await self.session.flush()

    async def revoke_one(self, token: RefreshToken, *, reason: RevokedReason) -> None:
        """Revoke a single token, leaving the rest of its family alone."""
        if token.revoked_at is not None:
            return
        token.revoked_at = datetime.now(UTC)
        token.revoked_reason = reason
        await self.session.flush()

    async def revoke_family(self, family_id: uuid.UUID, *, reason: RevokedReason) -> int:
        """Revoke every unrevoked token in one rotation chain. Returns the count.

        Scoped to the family, not the user: a replay means one device's chain leaked,
        and logging the user out of their other devices would be collateral damage.

        This is a bulk `UPDATE`, so `onupdate` does not fire — but `refresh_tokens` has
        no `updated_at`, so there is nothing to set. See `.claude/rules/persistence.md`.
        """
        result = await self.session.execute(
            update(RefreshToken)
            .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
            .values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        return cast(CursorResult[Any], result).rowcount

    async def revoke_all_for_user(
        self,
        user_id: uuid.UUID,
        *,
        reason: RevokedReason,
        except_token_id: uuid.UUID | None = None,
    ) -> int:
        """Revoke every unrevoked token for one user. Returns the count.

        `except_token_id` spares the caller's own session, which is what
        `docs/PRD.md:108` means by revoking all *other* refresh tokens on a password
        change.
        """
        statement = update(RefreshToken).where(
            RefreshToken.user_id == user_id, RefreshToken.revoked_at.is_(None)
        )
        if except_token_id is not None:
            statement = statement.where(RefreshToken.id != except_token_id)
        result = await self.session.execute(
            statement.values(revoked_at=datetime.now(UTC), revoked_reason=reason)
        )
        return cast(CursorResult[Any], result).rowcount

    async def delete_expired_and_revoked(self) -> int:
        """Hard-delete dead refresh tokens. Returns how many went.

        `refresh_tokens` is the documented exception to soft delete
        (`docs/PRD.md` §5.1): its lifecycle is `revoked_at` / `expires_at`, and these
        rows are genuinely finished.
        """
        now = datetime.now(UTC)
        result = await self.session.execute(
            delete(RefreshToken).where(
                or_(RefreshToken.expires_at < now, RefreshToken.revoked_at.is_not(None))
            )
        )
        return cast(CursorResult[Any], result).rowcount
