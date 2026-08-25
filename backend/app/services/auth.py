"""Login, rotation, password change, and revocation.

Every token-issuing method returns `(response, raw_refresh_token)`. The route sets the
cookie, so cookie attributes stay an HTTP concern and the service stays testable
without a request.
"""

import uuid
from datetime import UTC, datetime, timedelta

from fastapi import status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
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


class AuthService:
    """Business rules for `/auth`."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

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

    def _validate_new_password(self, password: str) -> str:
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

    async def _issue(
        self, user: User, *, family_id: uuid.UUID | None = None
    ) -> tuple[AccessTokenResponse, str]:
        """Mint an access token and a refresh token, storing only the latter's digest."""
        access_token, expires_in = create_access_token(
            user.id,
            secret=self.settings.secret_key,
            ttl_minutes=self.settings.access_token_ttl_minutes,
        )
        raw_refresh = generate_opaque_token()
        await self.tokens.create(
            user_id=user.id,
            family_id=family_id or uuid.uuid4(),
            token_hash=sha256_hex(raw_refresh),
            expires_at=datetime.now(UTC) + timedelta(days=self.settings.refresh_token_ttl_days),
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

    async def refresh(self, raw_token: str | None) -> tuple[AccessTokenResponse, str]:
        """Exchange a refresh token for a new pair, rotating it.

        Order matters. Expiry is checked before reuse so an honestly-stale token does
        not revoke a family; reuse inside the grace window mints a sibling rather than
        being treated as a replay (D12).
        """
        token = await self._load_token(raw_token)

        if token.revoked_at is not None:
            await self.tokens.revoke_family(token.family_id, reason="replay")
            await self.session.commit()
            raise self._invalid_token(ErrorCode.REFRESH_TOKEN_REUSED)

        if token.expires_at <= datetime.now(UTC):
            raise self._invalid_token(ErrorCode.TOKEN_EXPIRED)

        if token.used_at is not None:
            grace = timedelta(seconds=self.settings.refresh_rotation_grace_seconds)
            if datetime.now(UTC) - token.used_at > grace:
                await self.tokens.revoke_family(token.family_id, reason="replay")
                await self.session.commit()
                raise self._invalid_token(ErrorCode.REFRESH_TOKEN_REUSED)
            # Inside the window: two tabs raced. Mint a sibling in the same family.
            user = await self.users.get(token.user_id)
            if user is None:
                await self.tokens.revoke_family(token.family_id, reason="user_deactivated")
                await self.session.commit()
                raise self._invalid_token()
            issued = await self._issue(user, family_id=token.family_id)
            await self.session.commit()
            return issued

        user = await self.users.get(token.user_id)
        if user is None:
            await self.tokens.revoke_family(token.family_id, reason="user_deactivated")
            await self.session.commit()
            raise self._invalid_token()

        await self.tokens.mark_used(token)
        issued = await self._issue(user, family_id=token.family_id)
        await self.session.commit()
        return issued

    async def change_password(
        self, user_id: uuid.UUID, payload: ChangePasswordRequest, raw_token: str | None
    ) -> UserResponse:
        """Change the caller's own password, keeping their current session alive."""
        user = await self.users.get(user_id)
        if user is None:
            raise self._invalid_token()

        if not verify_password(payload.current_password, user.password_hash):
            raise self._invalid_credentials()

        user.password_hash = self._validate_new_password(payload.new_password)
        user.must_change_password = False
        user.updated_at = datetime.now(UTC)

        # Revoke all *other* sessions (docs/PRD.md:108). The caller's own token is
        # identifiable because it arrived in the cookie.
        current = await self.tokens.get_by_hash(sha256_hex(raw_token)) if raw_token else None
        await self.tokens.revoke_all_for_user(
            user.id,
            reason="password_change",
            except_token_id=current.id if current else None,
        )
        await self.session.commit()
        return UserResponse.model_validate(user)

    async def logout(self, raw_token: str | None) -> None:
        """Revoke the presented token. Idempotent — no cookie is not an error."""
        if not raw_token:
            return
        token = await self.tokens.get_by_hash(sha256_hex(raw_token))
        if token is not None:
            await self.tokens.revoke_one(token, reason="logout")
            await self.session.commit()

    async def logout_all(self, user_id: uuid.UUID) -> None:
        """Revoke every refresh token the caller holds."""
        await self.tokens.revoke_all_for_user(user_id, reason="logout_all")
        await self.session.commit()

    async def current(self, user_id: uuid.UUID) -> UserResponse:
        """The caller's full account row, including fields identity does not carry."""
        user = await self.users.get(user_id)
        if user is None:
            raise self._invalid_token()
        return UserResponse.model_validate(user)
