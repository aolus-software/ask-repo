"""Account provisioning and lifecycle.

Owns the rules, the transaction, and the orchestration across two repositories.
Imports no SQLAlchemy constructs — see `.claude/rules/persistence.md`.
"""

import uuid
from datetime import UTC, datetime

from fastapi import status
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.errors import AppError, ErrorCode
from app.core.passwords import PasswordPolicyError, check_password, get_common_passwords
from app.core.security import hash_password
from app.models.user import User
from app.repositories.refresh_token import RefreshTokenRepository
from app.repositories.user import UserRepository
from app.schemas.pagination import ListQuery, PaginatedResponse
from app.schemas.user import (
    ResetPasswordRequest,
    UserCreateRequest,
    UserResponse,
    UserUpdateRequest,
)

DEFAULT_SORT_FIELD = "created_at"


class UserService:
    """Business rules for `/users`."""

    def __init__(self, session: AsyncSession, settings: Settings) -> None:
        self.session = session
        self.settings = settings
        self.users = UserRepository(session)
        self.tokens = RefreshTokenRepository(session)

    def _hash(self, password: str) -> str:
        """Apply policy, then hash. One error code for every policy failure."""
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

    async def _load(self, user_id: uuid.UUID) -> User:
        """Fetch a live account or raise `404`."""
        user = await self.users.get(user_id)
        if user is None:
            raise AppError(status.HTTP_404_NOT_FOUND, ErrorCode.USER_NOT_FOUND, "No such user.")
        return user

    def _email_taken(self) -> AppError:
        return AppError(
            status.HTTP_409_CONFLICT,
            ErrorCode.EMAIL_ALREADY_EXISTS,
            "An account with that email already exists.",
        )

    async def _guard_last_admin(self, user: User) -> None:
        """Refuse an operation that would leave the instance with no admin (D17)."""
        if not user.is_admin:
            return
        if await self.users.count_active_admins(excluding=user.id) == 0:
            raise AppError(
                status.HTTP_409_CONFLICT,
                ErrorCode.LAST_ADMIN,
                "This is the only administrator account. Promote another admin first.",
            )

    async def list(self, query: ListQuery) -> PaginatedResponse[UserResponse]:
        """One page of accounts. Readable by any authenticated user (D15)."""
        try:
            rows, total = await self.users.list_page(
                page=query.page,
                limit=query.limit,
                search=query.search,
                sort=query.sort or DEFAULT_SORT_FIELD,
                descending=query.sort_direction == "desc",
            )
        except ValueError as error:
            raise AppError(
                status.HTTP_400_BAD_REQUEST,
                ErrorCode.INVALID_SORT_FIELD,
                f"Cannot sort by that field. Allowed: {sorted(self.users.SORTABLE_FIELDS)}.",
            ) from error

        return PaginatedResponse.build(
            [UserResponse.model_validate(row) for row in rows],
            page=query.page,
            limit=query.limit,
            total_count=total,
        )

    async def get(self, user_id: uuid.UUID) -> UserResponse:
        """One account by id."""
        return UserResponse.model_validate(await self._load(user_id))

    async def create(self, payload: UserCreateRequest) -> UserResponse:
        """Provision an account. `must_change_password` is set on every new account.

        The pre-check below is check-then-insert, not a lock: two admins creating the
        same address in one flush window can both pass it. `BaseRepository.add` flushes
        immediately, so the partial-unique-index violation surfaces there, not at
        `commit` — the `except IntegrityError` wraps both. It raises the same `409` the
        pre-check does, instead of a bare `500`. The pre-check stays because it is the
        common case and gives a cleaner message without a round trip to the database's
        error text.
        """
        if await self.users.email_exists(payload.email):
            raise self._email_taken()

        user = User(
            id=uuid.uuid4(),
            name=payload.name,
            email=payload.email,
            password_hash=self._hash(payload.password),
            is_admin=payload.is_admin,
            must_change_password=True,
        )
        try:
            await self.users.add(user)
            await self.session.commit()
        except IntegrityError as error:
            await self.session.rollback()
            raise self._email_taken() from error
        return UserResponse.model_validate(user)

    async def update(self, user_id: uuid.UUID, payload: UserUpdateRequest) -> UserResponse:
        """Partial update of name and the admin flag."""
        user = await self._load(user_id)

        if payload.is_admin is False:
            await self._guard_last_admin(user)

        if payload.name is not None:
            user.name = payload.name
        if payload.is_admin is not None:
            user.is_admin = payload.is_admin
        # `updated_at`'s `onupdate=func.now()` is a server-side expression: an ORM
        # UPDATE does not fetch it back via RETURNING the way an INSERT does, so it
        # is left expired on the Python object after commit. Setting it here, as
        # `reset_password` below already does, avoids a lazy load that `model_validate`
        # cannot perform outside an awaited context.
        user.updated_at = datetime.now(UTC)

        await self.session.commit()
        return UserResponse.model_validate(user)

    async def soft_delete(self, user_id: uuid.UUID) -> None:
        """Deactivate an account and end every session it holds.

        The token revocation is what makes `docs/PRD.md:101`'s "immediately" true for
        refresh; the middleware's per-request row load covers the access token.
        """
        user = await self._load(user_id)
        await self._guard_last_admin(user)
        await self.users.soft_delete(user)
        await self.tokens.revoke_all_for_user(user.id, reason="user_deactivated")
        await self.session.commit()

    async def reset_password(
        self, user_id: uuid.UUID, payload: ResetPasswordRequest
    ) -> UserResponse:
        """Set an admin-supplied temporary password and force a change on next login."""
        user = await self._load(user_id)
        user.password_hash = self._hash(payload.new_password)
        user.must_change_password = True
        user.updated_at = datetime.now(UTC)
        await self.tokens.revoke_all_for_user(user.id, reason="admin_reset")
        await self.session.commit()
        return UserResponse.model_validate(user)
