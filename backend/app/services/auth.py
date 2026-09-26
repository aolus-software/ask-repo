"""Login, rotation, password change, and revocation.

Every token-issuing method returns `(response, raw_refresh_token)`. The route sets the
cookie, so cookie attributes stay an HTTP concern and the service stays testable
without a request.
"""

import logging
import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.audit import AuditEntry, AuditEventType, AuditRecorder
from app.core.errors import AppError, ErrorCode
from app.core.passwords import validate_and_hash_new_password
from app.core.rate_limit import LoginAttemptLimiter
from app.core.security import (
    create_access_token,
    dummy_password_hash,
    generate_opaque_token,
    hash_password,
    needs_rehash,
    sha256_hex,
    verify_password,
)
from app.models.refresh_token import RefreshToken
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.auth import AccessTokenResponse, ChangePasswordRequest
from app.schemas.user import UserResponse

logger = logging.getLogger(__name__)

# `refresh_tokens.user_agent` is `String(255)`. A header is client-controlled and
# unbounded, so it is cut rather than rejected — a long agent is not an attack worth
# refusing a login over.
MAX_USER_AGENT_LENGTH = 255


class AuthService:
    """Business rules for `/auth`."""

    def __init__(
        self,
        session: AsyncSession,
        settings: Settings,
        attempts: LoginAttemptLimiter,
        *,
        recorder: AuditRecorder,
        client_ip: str | None = None,
        user_agent: str | None = None,
    ) -> None:
        self.session = session
        self.settings = settings
        self.attempts = attempts
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)
        self._recorder = recorder
        self._client_ip = client_ip
        self._user_agent = user_agent[:MAX_USER_AGENT_LENGTH] if user_agent else None

    # --- helpers -----------------------------------------------------------

    def _invalid_credentials(self) -> AppError:
        """One uniform failure, so login cannot be used to enumerate accounts."""
        return AppError(
            status.HTTP_401_UNAUTHORIZED,
            ErrorCode.INVALID_CREDENTIALS,
            "Incorrect email or password.",
        )

    def _invalid_token(self, code: ErrorCode = ErrorCode.INVALID_TOKEN) -> AppError:
        return AppError(status.HTTP_401_UNAUTHORIZED, code, "Session is no longer valid.")

    async def _issue(
        self,
        user: User,
        *,
        parent: RefreshToken | None = None,
        expires_at: datetime | None = None,
    ) -> tuple[AccessTokenResponse, str]:
        """Mint an access token and a refresh token, storing only the latter's digest.

        With no `parent` this starts a session: a new family, and the device this
        request came from. With one it continues that session: the parent's family,
        and the parent's device — a rotation arrives from the Next server, so its own
        agent and address describe the proxy, not the person.

        `expires_at` defaults to a fresh `now + refresh_token_ttl_days`. The grace-window
        sibling path (see `refresh`) passes the *parent's* `expires_at` instead, so a
        hijacked chain is capped at the original token's remaining lifetime rather than
        renewing itself indefinitely on every rotation.
        """
        family = parent.family_id if parent else uuid.uuid4()
        access_token, expires_in = create_access_token(
            user.id,
            secret=self.settings.secret_key,
            ttl_minutes=self.settings.access_token_ttl_minutes,
            session_id=family,
        )
        raw_refresh = generate_opaque_token()
        await self.tokens.create(
            user_id=user.id,
            family_id=family,
            token_hash=sha256_hex(raw_refresh),
            expires_at=expires_at
            or datetime.now(UTC) + timedelta(days=self.settings.refresh_token_ttl_days),
            user_agent=parent.user_agent if parent else self._user_agent,
            ip_address=parent.ip_address if parent else self._client_ip,
        )
        response = AccessTokenResponse(
            access_token=access_token,
            expires_in=expires_in,
            user=UserResponse.model_validate(user),
        )
        return response, raw_refresh

    async def _load_token(self, raw_token: str | None) -> RefreshToken:
        """Resolve a presented refresh token or raise `401`."""
        if not raw_token:
            raise self._invalid_token()
        token = await self.tokens.get_by_hash(sha256_hex(raw_token))
        if token is None:
            raise self._invalid_token()
        return token

    # --- operations --------------------------------------------------------

    async def login(self, email: str, password: str) -> tuple[AccessTokenResponse, str]:
        """Verify credentials and issue a new token pair.

        Only failed attempts count toward the per-email rate limit, and a success
        clears it — a raw per-email counter would otherwise be a lockout weapon
        (`app/core/rate_limit.py`). `check_email` runs outside the `try` so an address
        already over budget raises its own `429` rather than being counted again.

        Both outcomes are audited, and the failure branch is the reason this records
        here rather than in the route: the route sees a `401` and not whether the
        address matched an account, which is what decides whether the submitted string
        may be stored at all (`.claude/rules/audit-trail.md`).
        """
        await self.attempts.check_email(email)
        try:
            issued = await self._authenticate_and_issue(email, password)
        except Exception:
            await self.attempts.record_failure(email)
            await self._record_failed_login(email)
            raise
        await self.attempts.clear(email)
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_LOGIN_SUCCEEDED,
                actor_user_id=issued[0].user.id,
                actor_email=issued[0].user.email,
                ip_address=self._client_ip,
                context={"mustChangePassword": issued[0].user.must_change_password},
            )
        )
        return issued

    async def _record_failed_login(self, email: str) -> None:
        """Record the attempt, storing the address only if it names a live account.

        The submitted string is raw request input and people paste passwords into the
        email field. A match means the address is already in `users` and storing it
        adds nothing new; no match means it is an unvalidated string and stays out.
        What is given up is address-enumeration detail — `ip_address` still shows the
        pattern from one host.

        This runs from inside `except Exception` in `login`, on the request-scoped
        session. If the credential check failed for a database reason, that session
        is already poisoned and this lookup would raise `PendingRollbackError`,
        *replacing* the exception the caller is mid-handling with an audit-path
        error. The lookup is wrapped rather than left to propagate: `known = None` is
        the conservative default anyway, since it is exactly the "store no address"
        branch below.
        """
        try:
            known = await self.users.get_by_email(email)
        except Exception:
            logger.warning(
                "failed-login lookup could not run (session likely poisoned by the"
                " original failure); recording as an unknown account",
                exc_info=True,
            )
            known = None
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_LOGIN_FAILED,
                outcome="failure",
                actor_user_id=known.id if known else None,
                actor_email=known.email if known else None,
                target_type="user" if known else None,
                target_id=known.id if known else None,
                ip_address=self._client_ip,
                context={"unknownAccount": known is None},
            )
        )

    async def _authenticate_and_issue(
        self, email: str, password: str
    ) -> tuple[AccessTokenResponse, str]:
        """Verify credentials and issue a token pair, or raise.

        An unknown address is still verified against a dummy hash, so the response
        timing does not reveal whether the account exists (`docs/PRD.md:114`).
        """
        user = await self.users.get_by_email(email)
        if user is None:
            verify_password(password, dummy_password_hash(cost=self.settings.bcrypt_cost))
            raise self._invalid_credentials()

        if not verify_password(password, user.password_hash):
            raise self._invalid_credentials()

        # The cost factor lives in the stored hash, so raising it later reaches
        # existing accounts on their next login (D22).
        if needs_rehash(user.password_hash, cost=self.settings.bcrypt_cost):
            user.password_hash = hash_password(password, cost=self.settings.bcrypt_cost)

        user.last_login_at = datetime.now(UTC)
        # `onupdate=func.now()` is a server-side expression: touching any column
        # expires `updated_at` after the flush `_issue` triggers below, and reading an
        # expired attribute outside an awaited context is what `UserResponse.model_validate`
        # would do next. Setting it eagerly avoids that lazy load, matching the pattern
        # `UserService.update` and `.reset_password` already use.
        user.updated_at = datetime.now(UTC)
        issued = await self._issue(user)
        await self.session.commit()
        return issued

    async def _record_refresh_replayed(
        self,
        family_id: uuid.UUID,
        revoked_count: int,
        *,
        actor_user_id: uuid.UUID,
        actor_email: str | None,
    ) -> None:
        """Record a genuine reuse of an already-rotated refresh token.

        Only the two branches that revoke the whole family call this — the grace-
        window sibling mint (D12) is a race between two tabs, not a replay, and does
        not record. `actor_user_id` is the token's own `user_id`: a replayed refresh
        token is a security signal, and whose account it happened on is the first
        thing a responder needs, so it is not left to `context`.
        """
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_REFRESH_REPLAYED,
                outcome="failure",
                actor_user_id=actor_user_id,
                actor_email=actor_email,
                ip_address=self._client_ip,
                context={"familyId": str(family_id), "revokedCount": revoked_count},
            )
        )

    async def refresh(self, raw_token: str | None) -> tuple[AccessTokenResponse, str]:
        """Exchange a refresh token for a new pair, rotating it.

        Order matters. Expiry is checked before reuse so an honestly-stale token does
        not revoke a family; reuse inside the grace window mints a sibling rather than
        being treated as a replay (D12).
        """
        token = await self._load_token(raw_token)

        if token.expires_at <= datetime.now(UTC):
            raise self._invalid_token(ErrorCode.TOKEN_EXPIRED)

        if token.revoked_at is not None:
            revoked_count = await self.tokens.revoke_family(token.family_id, reason="replay")
            await self.session.commit()
            replayed_user = await self.users.get(token.user_id)
            await self._record_refresh_replayed(
                token.family_id,
                revoked_count,
                actor_user_id=token.user_id,
                actor_email=replayed_user.email if replayed_user is not None else None,
            )
            raise self._invalid_token(ErrorCode.REFRESH_TOKEN_REUSED)

        if token.used_at is not None:
            grace = timedelta(seconds=self.settings.refresh_rotation_grace_seconds)
            if datetime.now(UTC) - token.used_at > grace:
                revoked_count = await self.tokens.revoke_family(token.family_id, reason="replay")
                await self.session.commit()
                replayed_user = await self.users.get(token.user_id)
                await self._record_refresh_replayed(
                    token.family_id,
                    revoked_count,
                    actor_user_id=token.user_id,
                    actor_email=replayed_user.email if replayed_user is not None else None,
                )
                raise self._invalid_token(ErrorCode.REFRESH_TOKEN_REUSED)
            # Inside the window: two tabs raced. Mint a sibling in the same family.
            user = await self.users.get(token.user_id)
            if user is None:
                await self.tokens.revoke_family(token.family_id, reason="user_deactivated")
                await self.session.commit()
                raise self._invalid_token()
            issued = await self._issue(user, parent=token, expires_at=token.expires_at)
            await self.session.commit()
            return issued

        user = await self.users.get(token.user_id)
        if user is None:
            await self.tokens.revoke_family(token.family_id, reason="user_deactivated")
            await self.session.commit()
            raise self._invalid_token()

        await self.tokens.mark_used(token)
        issued = await self._issue(user, parent=token)
        await self.session.commit()
        return issued

    async def change_password(
        self,
        user_id: uuid.UUID,
        payload: ChangePasswordRequest,
        session_id: uuid.UUID | None,
    ) -> UserResponse:
        """Change the caller's own password, keeping their current session alive."""
        user = await self.users.get(user_id)
        if user is None:
            raise self._invalid_token()

        if not verify_password(payload.current_password, user.password_hash):
            raise self._invalid_credentials()

        # Captured before the change: `change_password` is what clears the flag, so
        # reading it afterwards would record `False` for every call and the `forced`
        # context key would be useless.
        was_forced = user.must_change_password

        user.password_hash = validate_and_hash_new_password(payload.new_password, self.settings)
        user.must_change_password = False
        user.updated_at = datetime.now(UTC)

        # Revoke all *other* sessions (docs/PRD.md:108). The caller's session is the one
        # their access token names: the refresh cookie never reaches this route through
        # the BFF proxy. A token minted before `sid` names none, so every session goes —
        # the old behaviour, for at most one access-token lifetime after deploy.
        await self.tokens.revoke_all_for_user(
            user.id, reason="password_change", except_family_id=session_id
        )
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_PASSWORD_CHANGED,
                actor_user_id=user.id,
                actor_email=user.email,
                ip_address=self._client_ip,
                context={"forced": was_forced},
            )
        )
        return UserResponse.model_validate(user)

    async def logout(self, raw_token: str | None) -> None:
        """Revoke the presented token. Idempotent — no cookie is not an error."""
        if not raw_token:
            return
        token = await self.tokens.get_by_hash(sha256_hex(raw_token))
        if token is not None:
            await self.tokens.revoke_one(token, reason="logout")
            await self.session.commit()
            await self._recorder.record(
                AuditEntry(
                    event_type=AuditEventType.AUTH_LOGOUT,
                    actor_user_id=token.user_id,
                    ip_address=self._client_ip,
                    context={"scope": "session"},
                )
            )

    async def logout_all(self, user_id: uuid.UUID) -> None:
        """Revoke every refresh token the caller holds."""
        await self.tokens.revoke_all_for_user(user_id, reason="logout_all")
        await self.session.commit()
        await self._recorder.record(
            AuditEntry(
                event_type=AuditEventType.AUTH_LOGOUT,
                actor_user_id=user_id,
                ip_address=self._client_ip,
                context={"scope": "all"},
            )
        )

    async def current(self, user_id: uuid.UUID) -> UserResponse:
        """The caller's full account row, including fields identity does not carry."""
        user = await self.users.get(user_id)
        if user is None:
            raise self._invalid_token()
        return UserResponse.model_validate(user)
