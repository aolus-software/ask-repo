"""Shared route dependencies.

These are this codebase's guards (`.claude/rules/router.md`). There is deliberately no
`require_password_changed`: the gate is enforced by `AuthContextMiddleware`, so it
cannot be forgotten on a new route.
"""

from collections.abc import AsyncIterator
from typing import Annotated

from fastapi import Depends, Request, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.audit import AuditRecorder
from app.core.errors import AppError, ErrorCode
from app.core.middleware import AuthContext, AuthenticatedUser
from app.core.rate_limit import client_ip
from app.db.session import get_session, get_sessionmaker


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


def get_audit_recorder() -> AuditRecorder:
    """The audit writer, on its own session.

    Built from the sessionmaker rather than from `SessionDep` deliberately: the write
    happens *after* the service commits, and a persistence guarantee should not rest
    on when FastAPI closes the request's `AsyncExitStack`. Lazy construction means a
    settings override in a test reaches it, the same way it reaches the middleware.
    """
    return AuditRecorder(get_sessionmaker())


def get_client_ip(
    request: Request, settings: Annotated[Settings, Depends(get_settings)]
) -> str | None:
    """The source host, for the auth events that record one.

    Resolved by `rate_limit.client_ip`, which is the **one** implementation of "who is
    calling" in this codebase. Keeping a second, simpler one here is what put two
    different answers in front of two readers: the limiter was `X-Forwarded-For`-aware
    while this returned the direct peer, so behind the BFF every audit row recorded the
    Next server. `docs/PRD.md` §3.4 leans on this value — a failed login against an
    unknown address deliberately stores no email, and the address is the only thing
    left that keeps an enumeration attempt visible as a pattern from one host.

    `None` rather than `"unknown"` because the column is nullable and a literal is a
    value an operator would have to learn to read as absence.
    """
    address = client_ip(request, trusted_proxy_hops=settings.trusted_proxy_hops)
    return None if address == "unknown" else address


CurrentUser = Annotated[AuthenticatedUser, Depends(get_current_user)]
AdminUser = Annotated[AuthenticatedUser, Depends(require_admin)]
SessionDep = Annotated[AsyncSession, Depends(session_dependency)]
AuditRecorderDep = Annotated[AuditRecorder, Depends(get_audit_recorder)]
ClientIpDep = Annotated[str | None, Depends(get_client_ip)]
