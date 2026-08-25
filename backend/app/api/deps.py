"""Shared route dependencies.

These are this codebase's guards (`.claude/rules/router.md`). There is deliberately no
`require_password_changed`: the gate is enforced by `AuthContextMiddleware`, so it
cannot be forgotten on a new route.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthContext, AuthenticatedUser
from app.db.session import get_session


async def session_dependency() -> AsyncIterator[AsyncSession]:
    """Re-exported so routes depend on this module rather than on `app.db`."""
    async for session in get_session():
        yield session


def get_current_user(request: Request) -> AuthenticatedUser:
    """The caller, as resolved by `AuthContextMiddleware`.

    A missing `request.state.auth` means the middleware is not installed. That is a
    programming error, so it surfaces as a 500 rather than a 401 — a 401 would send
    someone hunting for a credential problem that does not exist.
    """
    auth: AuthContext | None = getattr(request.state, "auth", None)
    if auth is None:
        raise RuntimeError("AuthContextMiddleware is not installed; request.state.auth is unset")
    if auth.user is not None:
        return auth.user
    raise AppError(
        status.HTTP_401_UNAUTHORIZED,
        auth.error or ErrorCode.INVALID_TOKEN,
        "Authentication is required.",
    )


def require_admin(
    current_user: Annotated[AuthenticatedUser, Depends(get_current_user)],
) -> AuthenticatedUser:
    """The caller, required to be an admin."""
    if not current_user.is_admin:
        raise AppError(
            status.HTTP_403_FORBIDDEN,
            ErrorCode.ADMIN_REQUIRED,
            "This action requires an administrator account.",
        )
    return current_user


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
SessionDep = Annotated[AsyncSession, Depends(session_dependency)]
