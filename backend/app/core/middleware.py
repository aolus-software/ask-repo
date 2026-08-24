"""Per-request identity, and the forced-password-change gate.

The middleware establishes identity for **every** request, then applies the `403` only
outside the exempt prefixes. Doing it the other way round — returning early for exempt
paths — leaves `request.state.auth` unset on `/auth` routes, so `GET /auth/me` fails
with a RuntimeError instead of returning the caller.

Why a middleware rather than a dependency: a route added later is gated with no action
taken. Why the user row is loaded every request rather than trusted from the token:
`docs/PRD.md:101` requires deactivating someone to end their sessions immediately, and
a stateless 15-minute token cannot deliver that.

Registration order matters. Starlette's `add_middleware` inserts at index 0 and the
stack is built reversed, so the last-added middleware is outermost. This one is
registered **before** `CORSMiddleware` so CORS ends up outside it and the gate's 403
carries the headers a browser needs to surface the body.
"""

import logging
import uuid
from dataclasses import dataclass

from fastapi import Request, Response, status
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint

from app.config import get_settings
from app.core.errors import ErrorCode, error_detail
from app.core.security import TokenExpiredError, TokenInvalidError, decode_access_token
from app.db.session import get_sessionmaker
from app.repositories.user import UserRepository

logger = logging.getLogger(__name__)

# Paths where a pending password change does not block the request. The whole `/auth`
# surface is exempt so a user can see who they are, keep a live token while typing,
# and log out (docs/PRD.md §4.0). `/` is matched exactly, not as a prefix.
GATE_EXEMPT_PREFIXES: tuple[str, ...] = (
    "/auth",
    "/health",
    "/docs",
    "/redoc",
    "/openapi.json",
)

_BEARER_PREFIX = "Bearer "


@dataclass(frozen=True, slots=True)
class AuthenticatedUser:
    """Request-scoped identity.

    A frozen snapshot rather than the ORM row: the middleware's session is closed
    before the handler runs, so passing the row would hand every handler a detached
    instance. Services load the full row when they need to mutate it.
    """

    id: uuid.UUID
    name: str
    email: str
    is_admin: bool
    # Carried because /auth routes run with the gate bypassed and may legitimately
    # observe it as true. Outside /auth, the gate has established it is false.
    must_change_password: bool


@dataclass(frozen=True, slots=True)
class AuthContext:
    """What the middleware resolved: a user, or the reason it could not."""

    user: AuthenticatedUser | None
    error: ErrorCode | None


def _is_gate_exempt(path: str) -> bool:
    """Whether a pending password change is tolerated on this path."""
    if path == "/":
        return True
    return path.startswith(GATE_EXEMPT_PREFIXES)


class AuthContextMiddleware(BaseHTTPMiddleware):
    """Decode the bearer token, load the user, and enforce the password-change gate."""

    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        auth = await self._resolve(request)
        request.state.auth = auth

        if (
            auth.user is not None
            and auth.user.must_change_password
            and not _is_gate_exempt(request.url.path)
        ):
            return JSONResponse(
                status_code=status.HTTP_403_FORBIDDEN,
                content={
                    "detail": error_detail(
                        ErrorCode.PASSWORD_CHANGE_REQUIRED,
                        "You must change your password before using the rest of the API.",
                    )
                },
            )

        return await call_next(request)

    async def _resolve(self, request: Request) -> AuthContext:
        """Establish identity, or record why it could not be established.

        Never raises: a `401` is the dependency's job, so an unauthenticated request to
        a public route is unaffected by anything decided here.
        """
        header = request.headers.get("Authorization", "")
        if not header.startswith(_BEARER_PREFIX):
            return AuthContext(user=None, error=None)

        settings = get_settings()
        try:
            user_id = decode_access_token(
                header.removeprefix(_BEARER_PREFIX), secret=settings.secret_key
            )
        except TokenExpiredError:
            return AuthContext(user=None, error=ErrorCode.TOKEN_EXPIRED)
        except TokenInvalidError:
            return AuthContext(user=None, error=ErrorCode.INVALID_TOKEN)

        # A session of its own: middleware cannot use `Depends`, and this one closes
        # before the handler's session opens.
        async with get_sessionmaker()() as session:
            user = await UserRepository(session).get(user_id)

        if user is None:
            # Covers both "never existed" and "soft-deleted since the token was issued".
            return AuthContext(user=None, error=ErrorCode.INVALID_TOKEN)

        return AuthContext(
            user=AuthenticatedUser(
                id=user.id,
                name=user.name,
                email=user.email,
                is_admin=user.is_admin,
                must_change_password=user.must_change_password,
            ),
            error=None,
        )
