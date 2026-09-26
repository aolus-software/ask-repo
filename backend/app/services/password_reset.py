"""Self-service password reset (docs/PRD.md §2.1, Phase 2.4; spec §6).

Three properties hold here and nowhere else:

- **No enumeration.** `request` answers the same for every address; the route sends
  after the response so a live account is not measurably slower.
- **Only the hash is stored.** The raw token lives in memory from mint to send and is
  handed to `deliver_password_reset` as an argument. Nothing could rebuild it, so
  nothing retries it — a user whose email did not arrive requests another.
- **Confirm ends every session**, as an admin reset does, and clears
  `must_change_password`, because the user chose this password themselves.
"""

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from app.config import Settings
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder
from app.core.errors import AppError, ErrorCode
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
from app.core.security import generate_opaque_token, hash_password, sha256_hex
from app.mail.compose import compose_password_reset
from app.mail.sender import MailSender, MailSendError
from app.models import PasswordResetToken
from app.repositories.password_reset_token import PasswordResetTokenRepository
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.password_reset import PasswordResetConfirm, PasswordResetRequest

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class PendingResetEmail:
    """What the background task needs to send. `raw_token` exists nowhere else."""

    token_id: uuid.UUID
    raw_token: str
    to: str


class PasswordResetService:
    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        *,
        recorder: AuditRecorder,
        client_ip: str | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = PasswordResetTokenRepository(session)
        self.refresh_tokens = RefreshTokenRepository(session)
        self._recorder = recorder
        self._client_ip = client_ip

    async def request(self, payload: PasswordResetRequest) -> PendingResetEmail | None:
        """Mint a token for a live account; return `None`, silently, for anything else."""
        if not self.settings.mail_enabled:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.PASSWORD_RESET_UNAVAILABLE,
                "Password reset by email is not available on this instance. Ask an administrator.",
            )

        user = await self.users.get_by_email(payload.email)
        pending: PendingResetEmail | None = None
        if user is not None:
            raw_token = generate_opaque_token()
            now = datetime.now(UTC)
            await self.tokens.revoke_live_for_user(user.id)
            token = await self.tokens.add(
                PasswordResetToken(
                    id=uuid.uuid4(),
                    user_id=user.id,
                    token_hash=sha256_hex(raw_token),
                    created_at=now,
                    expires_at=now
                    + timedelta(minutes=self.settings.password_reset_token_ttl_minutes),
                )
            )
            await self.session.commit()
            pending = PendingResetEmail(token_id=token.id, raw_token=raw_token, to=user.email)

        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_PASSWORD_RESET_REQUESTED,
                actor_user_id=user.id if user else None,
                actor_email=user.email if user else None,
                target_type="user" if user else None,
                target_id=user.id if user else None,
                ip_address=self._client_ip,
                context={"unknownAccount": user is None},
            )
        )
        return pending

    async def confirm(self, payload: PasswordResetConfirm) -> None:
        """Spend a token: new password, flag cleared, every session revoked."""
        token = await self.tokens.get_usable_by_hash(sha256_hex(payload.token))
        user = await self.users.get(token.user_id) if token else None
        if token is None or user is None or user.deleted_at is not None:
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.PASSWORD_RESET_TOKEN_INVALID,
                "This reset link is invalid or has expired. Request a new one.",
            )

        user.password_hash = self._validate_new_password(payload.new_password)
        user.must_change_password = False
        user.updated_at = datetime.now(UTC)
        token.used_at = datetime.now(UTC)
        revoked = await self.refresh_tokens.revoke_all_for_user(user.id, reason="password_reset")
        await self.session.commit()

        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_PASSWORD_RESET_COMPLETED,
                actor_user_id=user.id,
                actor_email=user.email,
                target_type="user",
                target_id=user.id,
                ip_address=self._client_ip,
                context={"revokedCount": revoked},
            )
        )

    def _validate_new_password(self, password: str) -> str:
        # Mirrors AuthService._validate_new_password: one policy, one error code.
        try:
            check_password(
                password,
                min_length=self.settings.password_min_length,
                max_bytes=self.settings.password_max_bytes,
                common=get_common_passwords(),
            )
        except PasswordPolicyError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST, ErrorCode.WEAK_PASSWORD, error.reason
            ) from error
        return hash_password(password, cost=self.settings.bcrypt_cost)


async def deliver_password_reset(
    pending: PendingResetEmail,
    *,
    sender: MailSender,
    settings: Settings,
    sessionmaker: async_sessionmaker[AsyncSession],
) -> None:
    """Send once, after the response. Never raises, never retries (spec §6.2).

    Opens its own session: this runs after the request's session has closed.
    """
    email = compose_password_reset(raw_token=pending.raw_token, to=pending.to, settings=settings)
    try:
        await sender.send(email)
    except MailSendError as error:
        logger.warning(
            "reset email for token %s not sent (retryable=%s): %s",
            pending.token_id,
            error.retryable,
            error,
        )
        return
    try:
        async with sessionmaker() as session:
            await PasswordResetTokenRepository(session).mark_sent(pending.token_id)
            await session.commit()
    except Exception:
        # The email left; only the bookkeeping failed. Nothing reads sent_at to decide
        # anything, so this is a log line, not a failure.
        logger.warning("could not stamp sent_at on reset token %s", pending.token_id, exc_info=True)
